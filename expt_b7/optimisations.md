### Optimisation 1

Removed `BEGIN` and `COMMIT` from transactions that consist of a single SQL statement.

### Optimisation 2

Changed the distribution column of all tenant-owned tables to `merchant_id`.
The `merchants`, `customers`, `products`, `inventory`, `orders`, and
`order_items` tables are placed in the same explicit Citus colocation group.
Consequently, all rows belonging to one merchant are stored on corresponding
shards on the same worker. Merchant-scoped operations such as placing an order,
updating inventory, reading a customer's order history, and looking up a
product can therefore be routed to one worker instead of coordinating work
across unrelated shards.

The primary keys were changed to composite keys beginning with `merchant_id`,
for example `(merchant_id, customer_id)` and `(merchant_id, order_id)`. The
inventory table additionally has a unique constraint on
`(merchant_id, product_id)`, ensuring that a merchant has at most one inventory
record per product. Including the distribution column in every primary and
unique key is required because Citus cannot enforce uniqueness across
independent shards otherwise. The original entity-ID columns were retained so
that the existing data generator and transaction scripts remain compatible.

### Optimisation 3

Replaced the baseline single-column `merchant_id` indexes with indexes matched
to the actual filter, join, and ordering patterns of the workload:

- `orders (merchant_id, customer_id, created_at DESC, order_id)` supports T3 by
  finding a customer's newest orders in index order, avoiding a scan and sort
  of all orders belonging to that merchant.
- `order_items (merchant_id, order_id)` supports retrieving the items belonging
  to the selected orders. T3 must include `merchant_id` in the join predicate to
  make full use of this colocated index; that transaction rewrite is left for a
  later optimisation.
- `orders (created_at) INCLUDE (merchant_id, total_amount)` supports T6's date
  range filter and contains the columns required for its merchant revenue
  aggregation. When PostgreSQL can use an index-only scan, fewer heap pages need
  to be read.

Separate indexes containing only `merchant_id` were removed because the new
composite primary keys and workload-specific indexes already begin with that
column. Keeping the old indexes would consume storage and add index-maintenance
work without adding a distinct access path.

### Optimisation 4

Set the table fill factor to 80 for `inventory` and 85 for `orders`. This leaves
approximately 20% and 15% of each heap page free when the initial data is
loaded. These two tables receive frequent updates: T1, T2, and T7 change
inventory quantities, while T5 changes order status.

PostgreSQL implements an update by creating a new row version. Reserved space
makes it more likely that the new version can remain on the same heap page. As
the frequently changed columns (`quantity`, `updated_at`, and `order_status`)
are not part of secondary indexes, PostgreSQL may then perform a HOT update and
avoid creating new entries in every index. This trades somewhat larger tables
and more heap pages for potentially lower update, index-maintenance, and vacuum
costs under the write-heavy workload.

### Caveat: T7 (Inventory Transfer) does not benefit from colocation

T7 picks its source and destination product uniformly at random across the
_entire_ dataset (`random(1, NUM_PRODUCTS)`), so a transfer can, and often does,
move stock between two different merchants. Colocating rows by `merchant_id`
does nothing for a transaction that is not merchant-scoped to begin with: T7's
two `UPDATE`s can still land on two different shards on two different workers,
requiring Citus's distributed transaction coordination regardless of this
optimisation. Given that Workload B has more concentration on T7, we will need
to update our paritioning design in future optimizations. expt_b7 will serve
as a benchmark.

### Prev: expt_b4

This experiment moves `products` and `inventory` out of the merchant
colocation group into a colocation group of their own with a single shard, so
every product and inventory row lives on one worker. Everything else carried
over from `expt_b4` is unchanged, including `product_merchant_map` and the
routed T7, except for two adaptations that the new layout forces on T1 and on
data loading (below). Those are not optimisations; the layout does not run
without them.

### Motivation

`expt_b4` routes T7 to the shards that hold its two rows, but the source and
destination products are independent random draws. With `inventory` hashed over
32 shards on 4 workers, the two rows are on different workers for about 3 in 4
transfers, and those transfers commit with two-phase commit across two workers.
Routing removes T7's fan-out, but no single-column hash distribution can remove
that cross-worker commit, because it would need to place two unrelated random
products on the same worker.

Putting all of `inventory` in one shard does place them on the same worker.
Every T7 then writes to a single worker and commits in one phase.

### Why a single shard rather than distributing by product_id

Distributing `products` and `inventory` by `product_id` looks attractive for
workload B, since T7 (30%), T2 (10%), T4 (5%) and T9 (10%) all know the
`product_id`. But the two T7 rows would still hash to different workers 3 times
in 4, so T7 would keep its two-phase commit, while T1 would reserve up to five
products on up to five different shards. The single shard is the only layout
that removes the cross-worker commit from T7, so it is the one worth testing.

### Optimisation 1: products and inventory on a single shard

```sql
SELECT create_distributed_table('products', 'merchant_id', colocate_with => 'none', shard_count => 1);
SELECT create_distributed_table('inventory', 'merchant_id', colocate_with => 'products');
```

Both tables keep `merchant_id` as their distribution column, so their primary
keys, the `UNIQUE (merchant_id, product_id)` constraint and every query that
names `merchant_id` are unchanged. With one shard, `merchant_id` no longer
chooses between shards, but it still lets queries use those indexes. The two
tables stay colocated with each other, so T4's `products`/`inventory` join
still runs on one shard.

`create_schema` now also writes the placement of the single shard (worker
name and port) to `schema-create.log`, so the report can say which worker
carried this load.

`product_merchant_map` is kept exactly as in `expt_b4`, so that the only
difference in T7 between the two experiments is where the two `inventory` rows
live. The lookups still go to the map's shards on other workers, before
`BEGIN`. Replacing the map with an index on `inventory (product_id)` would
remove them, and is left as a possible follow-up.

### The trade-off being measured

| Transaction              | Weight | Change from `expt_b4`                                     |
| ------------------------ | ------ | --------------------------------------------------------- |
| T7 Inventory Transfer    | 30%    | both rows on one worker; one-phase commit                 |
| T2 Update Inventory      | 10%    | runs on the products/inventory worker                     |
| T4 Product Lookup        | 5%     | runs on the products/inventory worker                     |
| T9 Update Product        | 10%    | runs on the products/inventory worker                     |
| T1 Place Order           | 10%    | spans two colocation groups; usually two-phase commit     |
| T3, T5, T6, T8           | 35%    | unchanged                                                 |

T2, T4, T7 and T9 (55% of all transactions) now run entirely on one worker, and
T1 (another 10%) reserves its stock there too. That worker handles most of the
workload's writes on a quarter of the cluster's hardware. In return, T7, the
transaction that sets throughput in workload B, stops paying for a cross-worker
commit. Whether T7's cheaper commit outweighs the concentration on one worker
is what this experiment measures, and it could go either way.

Two smaller effects follow from the same change. A deadlock between two T7s is
now between two local transactions on one worker, so PostgreSQL detects it
itself instead of waiting for Citus's distributed deadlock detection. And all of
`products` and `inventory` (500,000 rows each) now share that one worker's 1 GB
of `shared_buffers`.

### Adaptation 1: T1 split into two statements

Since `expt_b3`, T1 has been a single statement that checks the customer,
checks and reserves stock, and inserts the order and its items. It runs as one
statement only because all five tables are colocated and every reference names
the same `merchant_id`, so Citus can send the whole statement to one shard. With
`products` and `inventory` in another colocation group, that is no longer
possible. The statement is split at the colocation boundary, inside the same
transaction:

1. **Statement 1, products and inventory.** It is identical to `expt_b4`'s
   eligibility check and reservation, except that the customer check is
   removed. It returns whether every requested product was reserved, plus the
   unit price of each item slot (`price_1` to `price_5`) through `\gset`,
   because statement 2 cannot read `products`.
2. **Statement 2, customers, orders and order_items** (runs only if statement
   1 reserved everything). It checks the customer and inserts the order and its
   items, with `unit_price` and `total_amount` computed from the prices
   returned by statement 1 instead of a join to `products`.
3. `COMMIT` if an order was created, otherwise `ROLLBACK`.

The result is the same as before. An order is created only when the customer
exists and every item was reserved, and otherwise nothing changes. Two
differences:

- The customer is now checked after stock is reserved. A missing customer rolls
  back the reservation instead of preventing it. This affects only the order in
  which locks are taken.
- An order that is not created now ends in `ROLLBACK`. `expt_b4` always
  committed, and the transaction changed nothing in that case.

Prices are read in statement 1 under the same transaction snapshot that
`expt_b4` used to read them, so a concurrent T9 is handled the same way as
before.

T1 now needs one more round trip. Whenever the merchant's shard is not on the
products/inventory worker (about 3 merchants in 4), the transaction also spans
two workers and commits in two phases. This is the cost the table above
charges to T1.

### Adaptation 2: order_items loading via a staging table

`generate_data` loads `order_items` by joining the generated rows (through
`orders`) to `products` to get each item's `price`. That join now crosses
colocation groups, which Citus does not push down. `run.sh` therefore adds a
loader-only table, `product_price_stage (merchant_id, product_id, price)`,
distributed by `merchant_id` in the merchant colocation group:

1. It is filled from `products` straight after `product_merchant_map`.
2. The `order_items` insert joins it instead of `products`, with the same join
   condition.
3. It is truncated immediately afterwards, before `orders.total_amount` is
   computed.

It is filled by reading `products`, not by recomputing prices from the
generator's formula, so the loaded data is identical to `expt_b4`'s. It is
empty for the whole benchmark and is part of every reset's `TRUNCATE`.

### What to look at when this is run

- **Placement.** Note from `schema-create.log` which worker holds the
  products/inventory shard, and check that worker's PostgreSQL log for errors
  or overload.
- **T7 latency** against `expt_b4` at 1 client, where there is no contention.
  This is the direct effect of the one-phase commit.
- **T2, T4 and T9 latency** as clients increase. These ran on all four workers
  in `expt_b4` and now share one. If they climb much faster than in `expt_b4`,
  that worker is saturating.
- **T1 latency** against `expt_b4`, for the cost of the split and of the
  cross-worker commit.
- **Overall throughput** at 64 clients against `expt_b4`. If the single worker
  saturates before T7 would have limited `expt_b4`, overall throughput will be
  lower than `expt_b4`'s, even though T7 itself is cheaper.
- **`pgbench_exit_code` and `failed_log_records`.** The T1 split and the loader
  change have not been run yet. A problem in either shows up as a failure in
  `data-generation.log` or as T1 errors in `benchmark.log`.

### Note: this experiment has not been run yet

This folder contains no `slurm-results/`.

### Prev: expt_b12

This experiment runs T1 (Place Order) as one distributed function, which Citus
delegates whole to the worker that holds the merchant's shards. The new order
and item ids are still drawn first, in a separate coordinator-only statement.
There is no change to the schema, data distribution, indexes, the other
transactions, or server parameters carried over from `expt_b12`.

### Motivation

`expt_b12` removed T6's scan of `orders`. Throughput went from
405.2 TPS in `expt_b11` to a peak of 1529.2 TPS at 8 clients, and 1099.8 TPS at 64. T1 is now the largest share of latency at low client counts and the second
largest at 64:

| Transaction            | Share at 1 client | Share at 8 clients | Share at 64 clients |
| ---------------------- | ----------------- | ------------------ | ------------------- |
| T1 Place Order         | 35.2%             | 37.5%              | 25.7%               |
| T6 Global Sales        | 32.0%             | 27.6%              | 42.3%               |
| T7 Inventory Transfer  | 23.1%             | 25.3%              | 22.8%               |
| T5 Update Order Status | 2.8%              | 2.8%               | 2.7%                |

T1 takes 21.3 ms at 1 client, while every single-shard statement in the
workload (T2, T4, T8, T9) costs about 1.2 ms end to end.

### Why T1 is slow

`expt_b12`'s `explain.log` shows T1's main statement is not routed. Citus plans
it recursively: every CTE becomes its own distributed subplan (`4_1` to `4_8`),
executed one after another, each passing its rows to the next as an
intermediate result, followed by the final query. `inserted_order` and
`inserted_items` both show `INSERT/SELECT method: pull to coordinator`, so the
rows travel to the coordinator and back. Add the `order_merchant_map` insert, the
rollup upsert and the two-phase commit, and T1 is roughly a dozen sequential
round trips.

### Optimisation: T1 as a distributed function

Citus has a mechanism for exactly this case, function call delegation. A
function marked as distributed, with a distribution argument and colocated
with the tables it uses, is sent whole to the worker that holds the shards for
that argument. There, its statements hit local shards through local execution
with cached plans. The Citus internals README describes it as the fix for "the
extra network round trips involved in each individual statement, even when
each statement goes to the same worker node".

`public.place_order` is defined at the end of `transactions/T1_place_order.sql`,
inside a `\if 0 ... \endif` block. pgbench never runs that block, since
`\if 0` is always false. `run.sh` extracts the lines between the two markers
in `create_schema` and runs them with psql once, after the tables are
distributed. They create the function and distribute it:

```sql
SELECT create_distributed_function(
  'public.place_order(bigint, bigint, bigint, integer, bigint[], integer[], bigint[])',
  'p_merchant_id',
  colocate_with => 'merchants'
);
```

T1 is now two statements with no transaction block:

```sql
SELECT nextval('benchmark_order_id_seq') AS order_id, ... \gset t1_

SELECT public.place_order(
  (:merchant_id)::bigint, (:customer_id)::bigint, (:t1_order_id)::bigint,
  (:item_count)::integer,
  ARRAY[...product ids...], ARRAY[...quantities...], ARRAY[...item ids...]
);
```

The function does, in order:

1. Check the customer belongs to the merchant.
2. For each distinct product, in `product_id` order, check that it exists and
   its inventory covers the combined quantity, and keep its price. If any check
   fails, return `false` before writing anything.
3. Decrement each product's inventory, in `product_id` order.
4. Insert the order, with `total_amount` summed from step 2.
5. Insert the items, in slot order, each at its product's price.
6. Upsert the `merchant_daily_sales` row for the order's `created_at::date`.
7. Insert the `order_merchant_map` row.

Steps 1 to 6 filter on `merchant_id` and touch only tables colocated with
`merchants`, so they run on the worker's local shards. Most are single-table
statements with an equality filter on `merchant_id`, which Citus plans on its
fast path. Step 7's table is sharded by `order_id`, so its row is usually on
another worker. The worker then coordinates the two-phase commit itself.

What crosses the network per T1 is now: the id draw to the coordinator (which
runs on the same node as pgbench), one call from the coordinator to the
worker, and, from that worker to one other, the map insert and the two-phase
commit's prepare and commit. Before, that was about a dozen sequential round
trips driven by the coordinator.

#### Conditions for delegation

These are checked in Citus's `function_call_delegation.c`. If any fails, the
function still runs correctly on the coordinator, only without the benefit.

- **No transaction block.** Inside `BEGIN ... COMMIT`, Citus does not delegate
  ("not pushing down function calls in a multi-statement transaction") unless
  the function is distributed with `force_delegation => true`. That flag pins
  every statement in the function to the one distribution key, which rules
  out the `order_merchant_map` insert. So T1 has no transaction block.
- **A bare call.** The statement must be `SELECT f(...)` on its own. A call
  inside a CTE or subquery is not delegated.
- **A constant distribution argument.** pgbench runs in simple query mode, so
  `(:merchant_id)::bigint` reaches Citus as a constant.
- **Metadata on the worker.** This is the default since Citus 11.
  The function block prints `hasmetadata` and `metadatasynced` for every
  node into `schema-create.log`.
- **Schema-qualified names.** Citus does not pass `search_path` to the worker.

### Why T1 still behaves like expt_b0

The data generator gives `inventory_id = product_id`, globally unique product,
customer and order ids, and order items that carry their order's
`merchant_id`. With those, and under `SERIALIZABLE` (the configured isolation
level on every node), T1 produces the same rows as `expt_b0`'s T1:

- **Atomicity.** Without `BEGIN ... COMMIT`, the call is one statement, and so
  one transaction. Any error rolls back every write in the function, including
  the `order_merchant_map` row through the worker's two-phase commit. Only the
  id draw is outside it, and `nextval` is never rolled back anyway, even in a
  transaction block.
- **Ids.** Every order and item id still comes from its sequence, so both are
  unique. `expt_b0` draws one order id per T1 as soon as the customer check
  passes, before any stock check, and the workload always picks an existing
  customer, so it draws one order id per T1. This version does the same.
  `expt_b12` drew one only when the order succeeded. Item ids ascend with
  `item_no`, as in `expt_b0`. On a failed order `expt_b0` drew item ids only up
  to the failing item, while this version has drawn all `item_count` of them;
  both leave the drawn ids unused. No transaction or check relies on ids being
  consecutive, and the actual values depend on how concurrent T1s interleave
  in every version, including `expt_b0`.
- **Stock check.** The same predicate as `expt_b9` onwards (customer exists;
  each product exists with inventory for its combined quantity), evaluated
  before any write; see the caveat there. It relies on `SERIALIZABLE`: all
  statements in the function share the transaction's snapshot, as `expt_b0`'s
  separate statements did, and a concurrent change to a checked row fails the
  decrement with a serialization error.
- **Rows and totals.** The order total is summed per product as combined
  quantity times price, which equals the per-item sum exactly because both are
  `NUMERIC`. Each item's `unit_price` is its product's price, read in the same
  snapshot as in `expt_b12`.
- **Rollup.** The upsert runs only when an order is inserted, adds the order's
  own `total_amount`, uses the order's own `created_at::date` (the expression
  the preload groups by), and commits with the order. The argument in
  `expt_b12/optimisations.md` that T6 returns the baseline's answer exactly
  carries over.
- **`created_at`.** Still `CURRENT_TIMESTAMP`, now the start time of the
  worker's transaction. It may differ from the coordinator's clock by
  milliseconds. No transaction depends on that, and the rollup day is taken
  from the stored `created_at`.
- **Retries.** A serialization failure inside the function reaches pgbench as
  SQLSTATE 40001, and pgbench retries the script from the start, with fresh
  ids.

Two timing changes, which can affect serialization failures and deadlocks but
not results: inventory rows are now locked in `product_id` order, and the
function runs in the worker's own transaction, under that node's
`default_transaction_isolation` of `SERIALIZABLE`.

### Recording plans

`explain/T1_place_order.sql` no longer wraps T1 in `BEGIN ... ROLLBACK`,
because Citus would not delegate the call inside a transaction block. It shows
the id draw with `ANALYZE`, and the call with `EXPLAIN (VERBOSE)` only, since
running it would commit an order. A delegated call shows as one `Task` on a
worker whose query is the call itself. The statements inside the function run
on the worker and do not appear in the plan.

### What to look at when this is run

- **`schema-create.log`.** `create_distributed_function` succeeds, and every
  worker shows `hasmetadata` and `metadatasynced` as `t`.
- **`explain.log`.** The call's plan is one `Task` on a worker whose query is
  the call itself. The id draw shows a plain local plan with no `Task`.
- **T1 latency at 1 client**, 21.7 ms in `expt_b12` (job-880152) and 23.8 ms in
  the first attempt. If delegated, it should be a few ms. If it stays near
  20 ms, delegation is not happening; check the plan in `explain.log`.
- **`serialization_failures` and `deadlock_failures`**, 127 and 0 at 64
  clients in `expt_b12`. A faster T1 means more overlap on hot merchants'
  inventory and rollup rows.
- **The next bottleneck.** Recompute the latency-share table. In the first
  attempt T6 was 40.5% at 64 clients and T7 22.8%.
- **Comparability.** Run on the same nodes as `expt_b12` (`xcnf[17-21]`).

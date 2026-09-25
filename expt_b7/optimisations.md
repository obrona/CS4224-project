### Prev: expt_b6

This experiment makes T1 (Place Order) run as one task on its merchant's shard
instead of a chain of distributed subplans. It draws the new order and item ids
in a separate coordinator-only statement first, and folds the
`merchant_daily_sales` upsert into T1's main statement. There is no change to
the schema, data distribution, indexes, the other transactions, or server
parameters carried over from `expt_b6`.

### Motivation

`expt_b6` (job-878914) removed T6's scan of `orders`. Throughput went from
405.2 TPS in `expt_b5` to a peak of 1529.2 TPS at 8 clients, and 1099.8 TPS at
64. T1 is now the largest share of latency at low client counts and the second
largest at 64:

| Transaction           | Share at 1 client | Share at 8 clients | Share at 64 clients |
| --------------------- | ----------------- | ------------------ | ------------------- |
| T1 Place Order        | 35.2%             | 37.5%              | 25.7%               |
| T6 Global Sales       | 32.0%             | 27.6%              | 42.3%               |
| T7 Inventory Transfer | 23.1%             | 25.3%              | 22.8%               |
| T5 Update Order Status| 2.8%              | 2.8%               | 2.7%                |

T1 takes 21.3 ms at 1 client, while every single-shard statement in the
workload (T2, T4, T8, T9) costs about 1.2 ms end to end.

### Why T1 is slow

`expt_b6`'s `explain.log` shows T1's main statement is not routed. Citus plans
it recursively: every CTE becomes its own distributed subplan (`4_1` to `4_8`),
executed one after another, each passing its rows to the next as an
intermediate result, followed by the final query. `inserted_order` and
`inserted_items` both show `INSERT/SELECT method: pull to coordinator`, so the
rows travel to the coordinator and back. Add the `order_merchant_map` insert, the
rollup upsert and the two-phase commit, and T1 is roughly a dozen sequential
round trips.

The likely cause is `nextval('benchmark_order_id_seq')` and
`nextval('benchmark_order_item_id_seq')`. `reset_benchmark_sequences` creates
them with a plain `CREATE SEQUENCE` on the coordinator, so they exist only
there. An `INSERT ... SELECT` whose target list calls them cannot be pushed to
a worker, and once one CTE cannot go to the shard, Citus plans the whole
statement CTE by CTE. Everything else in the statement names only constants
and tables filtered on the same `merchant_id`, which Citus can route. This is
read from the plan's shape; `expt_b6` ran T1 without `ANALYZE`, so there are
no per-step timings.

### Optimisation 1: draw the ids first

```sql
SELECT
  nextval('benchmark_order_id_seq') AS order_id,
  CASE WHEN (:item_count)::integer >= 1 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_1,
  ...
  CASE WHEN (:item_count)::integer >= 5 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_5
\gset t1_
```

The statement reads no table, so it runs on the coordinator without touching a
worker. `CASE` evaluates `nextval` only for the order's `item_count` items.
The ids then enter the main statement as constants: the order id directly, and
each item id as a fourth column of `input_items`, so item `k` keeps its own id
through `requested_items` to `inserted_items`.

### Optimisation 2: fold the rollup upsert into the statement

```sql
rollup AS (
  INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
  SELECT (:merchant_id)::bigint, o.created_at::date, 1, o.total_amount
  FROM inserted_order o
  ON CONFLICT (merchant_id, sales_date)
  DO UPDATE SET order_count = s.order_count + 1,
                revenue     = s.revenue + EXCLUDED.revenue
  RETURNING 1
)
```

`merchant_daily_sales` is colocated with `orders`, so this is on the same
shard as the rest of the statement. It replaces `expt_b6`'s separate upsert and
its `\gset` of the order's total and day.

The `order_merchant_map` insert stays a separate statement behind
`\if :t1_order_created`. That table is sharded by `order_id`, so it lives on a
different shard and cannot join a routed statement. T1 still has two commit
participants, as in `expt_b5` and `expt_b6`.

### Why T1 still behaves like expt_b0

The data generator gives `inventory_id = product_id`, globally unique product,
customer and order ids, and order items that carry their order's
`merchant_id`. With those, and under `SERIALIZABLE` (the configured isolation
level on every node), T1 produces the same rows as `expt_b0`'s T1:

- **Ids.** Every order and item id still comes from its sequence, so both are
  unique. `expt_b0` draws one order id per T1 as soon as the customer check
  passes, before any stock check, and the workload always picks an existing
  customer, so it draws one order id per T1. This version does the same.
  `expt_b6` drew one only when the order succeeded. Item ids ascend with
  `item_no`, as in `expt_b0`. On a failed order `expt_b0` drew item ids only up
  to the failing item, while this version has drawn all `item_count` of them;
  both leave the drawn ids unused. No transaction or check relies on ids being
  consecutive, and the actual values depend on how concurrent T1s interleave
  in every version, including `expt_b0`.
- **Stock check.** Unchanged from `expt_b3` onwards; see the caveat there. It
  relies on `SERIALIZABLE`.
- **Rows and totals.** `inserted_order`, `inserted_items` and the stock
  reservation are the same expressions as in `expt_b6`, with only the id
  source changed. As one statement, all CTEs share one snapshot, which is also
  what `expt_b0`'s separate statements saw under `SERIALIZABLE`.
- **Rollup.** The upsert inserts nothing when no order was inserted, adds the
  order's own `total_amount`, uses the order's own `created_at::date` (the
  expression the preload groups by), and commits with the order. The argument
  in `expt_b6/optimisations.md` that T6 returns the baseline's answer exactly
  carries over.
- **`created_at`.** Still `CURRENT_TIMESTAMP`, the transaction's start time.
  If Citus now evaluates it on the worker rather than the coordinator, it
  comes from a different clock by milliseconds. No transaction depends on
  that, and the rollup day is taken from the stored `created_at` either way.

The one timing change: the rollup row for the merchant and day is now locked
before the `order_merchant_map` round trip rather than after it. Locks are held
until commit anyway, so this adds about one round trip to how long the hot row
is held. It can affect serialization failures, not results.

### What to look at when this is run

- **`explain.log`.** T1's main statement should show `Task Count: 1` and no
  `Distributed Subplan`. The id draw should show a plain local plan with no
  `Task`. If subplans remain, Citus has refused to route something other than
  `nextval`; the most likely candidate is the `INSERT ... SELECT ... ON
  CONFLICT` in `rollup`. The transaction is still correct in that case, only
  slower.
- **T1 latency at 1 client**, 21.3 ms in `expt_b6`. If routed, it should be a
  few ms: the id draw, one routed statement, the map insert and the commit.
- **`serialization_failures`**, which rose to 114 at 64 clients in `expt_b6`.
  A faster T1 means more overlap on hot merchants' inventory and rollup rows.
- **The next bottleneck.** Recompute the latency-share table. T6 (42.3% at 64
  clients) and T7 (22.8%) are next.
- **Comparability.** Run on the same nodes as `expt_b6` (`xcnf[17-21]`).

### Note: this experiment has not been run yet

This folder contains no `slurm-results/`.

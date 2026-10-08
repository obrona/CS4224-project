### Prev: expt_b11

This experiment answers T6 (Global Sales) from a per-merchant, per-day revenue
rollup instead of scanning `orders`. There is no change to the schema of the
existing tables, to data distribution, to the other transactions, or to server
parameters carried over from `expt_b11`, apart from T1 maintaining the new
rollup.

### Motivation

`expt_b11` removed T5 as the bottleneck: T5's average latency fell from 1554.3 ms
to 28.5 ms at 64 clients. Overall throughput rose only from 367.1 to 405.2 TPS,
because T6 took over.

Each transaction's share of total measured latency in `expt_b11`
(`avg_latency_ms` x `successful_transactions`, over the workload total):

| Transaction            | Share at 1 client | Share at 64 clients |
| ---------------------- | ----------------- | ------------------- |
| T6 Global Sales        | 52.5%             | 65.4%               |
| T7 Inventory Transfer  | 16.6%             | 14.6%               |
| T1 Place Order         | 24.0%             | 13.6%               |
| T5 Update Order Status | 2.0%              | 1.8%                |

T6's latency across client counts is 42.9, 64.7, 128.5, 296.0, 565.4,
1030.2 ms. By Little's law 40.115 x 1.030 = 41.3, so about 41 of the 64 clients
are inside T6 at any moment. T6 is 10% of workload B, so 40.115 / 0.10 = 401
TPS, which is the observed overall throughput (405.2). T6 sets the ceiling.

### Why T6 is slow

T6 aggregates revenue per merchant over a rolling 30-day window:

```sql
SELECT merchant_id, COUNT(*), SUM(total_amount)
FROM orders
WHERE created_at >= CURRENT_TIMESTAMP - 30 * INTERVAL '1 day'
  AND created_at < CURRENT_TIMESTAMP
GROUP BY merchant_id
ORDER BY revenue DESC
LIMIT 20;
```

Unlike every earlier bottleneck, this one is not a routing problem. T6 spans
all merchants by definition, so no distribution column can prune it and no
rewrite can route it to one worker. Citus already does the right thing:
each shard computes partial per-merchant aggregates and the coordinator merges
them. The cost is the volume. The generator spreads 5,000,000 orders over 365
days, so a 30-day window covers roughly 411,000 order rows, and every T6
re-derives the same historical sums from scratch.

The only way to make it cheaper is to stop recomputing what cannot change.

### Optimisation 1: merchant_daily_sales

```sql
CREATE TABLE merchant_daily_sales (
  merchant_id BIGINT NOT NULL,
  sales_date  DATE   NOT NULL,
  order_count BIGINT NOT NULL,
  revenue     NUMERIC(14, 2) NOT NULL,
  PRIMARY KEY (merchant_id, sales_date)
);
SELECT create_distributed_table('merchant_daily_sales', 'merchant_id',
                                colocate_with => 'merchants');
```

`revenue` is `NUMERIC(14,2)` rather than `orders.total_amount`'s `(12,2)`
because one row sums many orders.

T6 filters on `sales_date` across all merchants, which is not a prefix of the
primary key, so a covering index makes that scan index-only:

```sql
CREATE INDEX idx_mds_period ON merchant_daily_sales (sales_date)
  INCLUDE (merchant_id, order_count, revenue);
```

It is preloaded in `generate_data` by aggregating `orders`, not by recomputing
the generator's formula:

```sql
INSERT INTO merchant_daily_sales (merchant_id, sales_date, order_count, revenue)
SELECT merchant_id, created_at::date, COUNT(*), SUM(total_amount)
FROM orders
GROUP BY merchant_id, created_at::date;
```

This must run **after** `generate_data`'s `UPDATE orders SET total_amount`.
Orders are inserted with `total_amount` 0.00 and backfilled from `order_items`
later; preloading any earlier records zero revenue for every merchant-day, and
nothing errors — the benchmark would simply produce a wrong T6.

The table is in the `TRUNCATE` for every reset and is covered by the
whole-database `ANALYZE` at the end of `generate_data`.

### Optimisation 2: T1 maintains the rollup

`inserted_order` now returns `total_amount` and `created_at` alongside
`order_id`, and T1 adds one upsert inside its existing transaction:

```sql
INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
VALUES ((:merchant_id)::bigint, DATE '2000-01-01' + (:t1_new_order_day)::integer, 1, (:t1_new_order_total)::numeric(12,2))
ON CONFLICT (merchant_id, sales_date)
DO UPDATE SET order_count = s.order_count + 1,
              revenue     = s.revenue + EXCLUDED.revenue;
```

Unlike `order_merchant_map`, this costs no extra commit participant.
`merchant_daily_sales` is distributed by `merchant_id` and colocated with
`orders`, so the upsert lands on the same shard as the order T1 just inserted.
T1 keeps exactly the two participants it had in `expt_b11`.

The bucket is the inserted order's own `created_at::date`, returned by
`inserted_order` as a day number (`created_at::date - DATE '2000-01-01'`)
because pgbench substitutes variables unquoted. It is the same expression the
preload groups by, so an order and its rollup contribution always share a day.

### Optimisation 3: T6 reads the rollup and the boundary day

Day buckets cannot express a rolling `CURRENT_TIMESTAMP` boundary. The day
containing the window start is therefore read from `orders` with the baseline's
own predicate, and only the whole days after it come from the rollup:

```sql
WITH partial_day AS (   -- from orders, one day, baseline predicate kept intact
  ... WHERE o.created_at >= CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day'
        AND o.created_at <  CURRENT_TIMESTAMP
        AND o.created_at <  (CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day')::date + 1
),
whole_days AS (         -- from the rollup
  ... WHERE s.sales_date >= (CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day')::date + 1
)
SELECT merchant_id, SUM(order_count), SUM(revenue)
FROM (partial_day UNION ALL whole_days) combined
GROUP BY merchant_id ORDER BY revenue DESC LIMIT 20;
```

The `created_at < CURRENT_TIMESTAMP` upper bound is kept verbatim even though
no visible order can have a future `created_at`, so the scan side stays
textually the baseline's. `CURRENT_TIMESTAMP` is fixed for the whole
transaction, so both branches see the same window.

Rows touched per T6: about 13,700 for the boundary day plus about 30,000
rollup rows (1,000 merchants x 30 days), against roughly 411,000 order rows
before � close to a 9x reduction, on much narrower tuples.

### Why this returns the baseline's answer exactly

Let `W` be the window start, `CURRENT_TIMESTAMP - REPORT_DAYS days`, `N` be
`CURRENT_TIMESTAMP` and `D` be `W::date`.

- **Disjoint.** Every order in `partial_day` has `created_at` in `[W, D+1)`, and
  since `W >= D` they all fall in bucket `D`. `whole_days` starts at bucket
  `D+1`. No order is counted twice.
- **Covering.** `partial_day` covers `[W, D+1)` and `whole_days` covers
  `[D+1, infinity)`, so together they cover `[W, infinity)`, which contains the
  baseline's `[W, N)`. Nothing lands beyond `N`, because `created_at` is the
  inserting transaction's start time and T6 only sees committed rows, so
  `created_at < commit < T6's snapshot`.
- **Consistent.** The upsert is in T1's transaction, so any snapshot sees an
  order and its rollup contribution together. This is what makes reading two
  sources safe; an asynchronous rollup would let T6 see an order in `orders`
  that no bucket had counted yet.
- **Stable summands.** T5 writes `order_status`, T9 writes product `price`, and
  nothing deletes orders, so an order's contribution is fixed at insert. Note
  this depends on `expt_b9`'s set-based T1, which computes `total_amount`
  inline; `expt_b8`'s trailing `UPDATE orders SET total_amount` would have made
  buckets drift.
- **Exact arithmetic.** `total_amount` is `NUMERIC`, so summing per-day
  subtotals gives bit-identical results to summing the orders directly. With
  `DOUBLE PRECISION` this would not hold.

The only visible difference is a type label: the baseline's `COUNT(*)` is
`bigint` while `SUM(order_count)` is `numeric`.

### What this does not assume about the data

The rollup is built by aggregating `orders`, maintained for whatever T1
creates, and the boundary day is computed from `orders` with the exact
predicate. None of that depends on how the synthetic data was generated.

This is worth stating because the naive version of this optimisation — reading
only the rollup, with `sales_date >= (win_start)::date` — _would_ have depended
on it. The generator gives every order at a given day-offset an identical
timestamp, so the boundary day is a solid block of about 13,700 orders that
falls entirely in or entirely out depending on the time of day the job started
and how long it has been running. The two-way split removes that.

What does depend on the data is the size of the win, not the answer. Because
`(i * 31) % 365` cycles evenly, days hold about 13,700 orders each and the
boundary scan is cheap. Skewed data would make `partial_day` more expensive
while still returning the correct result.

### Recording plans

After data generation, `run.sh` writes `explain.log` with an
`EXPLAIN (ANALYZE, VERBOSE, BUFFERS)` of every statement T1 to T9 runs. The
scripts are in `explain/`, one per transaction. They are psql rather than
pgbench scripts, because the transaction files rely on pgbench's `random()`
and `\if` expressions: each takes merchant 1, its lowest-numbered customer or
products, order 1 and a transfer between merchants 1 and 2 from the loaded
data, and follows the routed path. Writes run inside `BEGIN` ... `ROLLBACK`.

Each script is run once untimed to warm the cache and then again with its
output kept. `VERBOSE` shows the SQL sent to the shards, and `ANALYZE` shows
one sample shard's plan. The step runs outside the timed benchmark, and a
failing script is reported in the log without stopping the job.

**The `explain/` scripts duplicate the statements in `transactions/`.** A
change to a transaction must be copied into its explain script, or the log
will describe the old query.

### Possible refinement

T1's upsert is a second statement to a worker already in the transaction. It
could instead be folded into T1's single statement as another data-modifying
CTE reading `inserted_order`, saving one round trip. That was left out here
because `ON CONFLICT` inside a distributed multi-CTE statement is the least
proven part of the pattern, and a failed run costs a full job.

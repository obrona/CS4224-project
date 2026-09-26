### Prev: expt_a3

This experiment answers T6 (Global Sales) from a per-merchant, per-day revenue
rollup instead of scanning `orders`. It is a port of `expt_b6` onto the A-side
design, applied to `expt_a3` alone: it does not include `expt_a4`'s T5
routing. Apart from T1 maintaining the new rollup, there is no change to the
schema, data distribution, indexes, the other transactions, or server
parameters carried over from `expt_a3`.

This is one cell of the 2x2 described in `expt_a4/optimisations.md`:
`expt_a4` is T5 routing alone, this is the T6 rollup alone, and `expt_a6` is
both.

### Motivation

Each transaction's share of total measured latency in `expt_a3`
(`avg_latency_ms` x `successful_transactions`, over the workload total):

| Transaction            | Share at 1 client | Share at 8 clients | Share at 64 clients |
| ---------------------- | ----------------- | ------------------ | ------------------- |
| T1 Place Order         | 54%               | 47%                | 9%                  |
| T6 Global Sales        | 23%               | 20%                | 4%                  |
| T7 Inventory Transfer  | 14%               | 17%                | 6%                  |
| T5 Update Order Status | 6%                | 13%                | 81%                 |

T6 is 5% of workload A, but at 51.7 ms (1 client) and 97.7 ms (8 clients) it
is the slowest transaction per execution below saturation, and the second
largest share of latency there. At 64 clients it is hidden behind T5, which
`expt_a4` targets; `expt_a6` shows how much of T6 remains once T5 is routed.

### Why T6 is slow

T6 aggregates every order in the last `REPORT_DAYS` days across all merchants.
It cannot be routed by construction: every worker scans its share of
`orders` by `created_at` through `idx_orders_sales_period`, and the coordinator
merges the partial aggregates. The work grows with the number of orders in the
window, not with the 20 rows it returns.

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
CREATE INDEX idx_mds_period ON merchant_daily_sales (sales_date)
  INCLUDE (merchant_id, order_count, revenue);
```

It is filled in `generate_data` after `orders.total_amount` is computed, by
grouping `orders` on `(merchant_id, created_at::date)`, and it is part of the
`TRUNCATE` there. `revenue` is `NUMERIC(14,2)` rather than `(12,2)` because one
row sums many orders.

### Optimisation 2: T1 maintains the rollup

`inserted_order` now returns `total_amount` and `created_at`, and T1 adds one
upsert inside its existing transaction, only when an order was created:

```sql
INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
VALUES ((:merchant_id)::bigint, DATE '2000-01-01' + (:t1_new_order_day)::integer, 1, (:t1_new_order_total)::numeric(12,2))
ON CONFLICT (merchant_id, sales_date)
DO UPDATE SET order_count = s.order_count + 1,
              revenue     = s.revenue + EXCLUDED.revenue;
```

The rollup is colocated with `merchants`, so unlike `expt_a4`'s map write this
stays on the merchant's worker and T1 remains a single-worker transaction. It
does make every T1 for one merchant on one day contend on the same rollup row,
which is the cost to watch in workload A, where T1 is 36% of the mix.

### Optimisation 3: T6 reads the rollup and the boundary day

Day buckets cannot express the rolling `CURRENT_TIMESTAMP` window. The day
containing the window start is read from `orders` with the baseline's own
predicate, and only the whole days after it come from the rollup:

```sql
WITH partial_day AS (
  SELECT o.merchant_id, COUNT(*) AS order_count, SUM(o.total_amount) AS revenue
  FROM orders AS o
  WHERE o.created_at >= CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day'
    AND o.created_at < CURRENT_TIMESTAMP
    AND o.created_at < (CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day')::date + 1
  GROUP BY o.merchant_id
),
whole_days AS (
  SELECT s.merchant_id, SUM(s.order_count) AS order_count, SUM(s.revenue) AS revenue
  FROM merchant_daily_sales AS s
  WHERE s.sales_date >= (CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day')::date + 1
  GROUP BY s.merchant_id
)
SELECT merchant_id, SUM(order_count) AS order_count, SUM(revenue) AS revenue
FROM (SELECT * FROM partial_day UNION ALL SELECT * FROM whole_days) AS combined
GROUP BY merchant_id
ORDER BY revenue DESC
LIMIT 20;
```

### Why this returns the baseline's answer

The argument is the one in `expt_b6/optimisations.md` and carries over
unchanged: the two parts cover `[W, D+1)` and `[D+1, infinity)` for window
start `W` and `D = W::date`, so they are disjoint and together cover the
baseline's window; the upsert commits with its order, so every snapshot sees
an order and its rollup contribution together; an order's `total_amount` is
fixed at insert by `expt_a3`'s set-based T1 (no later `UPDATE`); and
`NUMERIC` sums are exact. The only visible difference is that `order_count` is
`numeric` instead of `bigint`.

### What to look at when this is run

- **T6 latency at 1 and 8 clients**, 51.7 ms and 97.7 ms in `expt_a3`.
- **T1 latency at 1 client**, 17.2 ms in `expt_a3`, for the cost of the
  upsert, and **`serialization_failures`** at high client counts for the cost
  of contention on hot merchants' rollup rows.
- **`pgbench_exit_code`**, which must be 0 for every client count.
- **Comparability.** Pinned to `xcnf[1,3-6]`, the same nodes as `expt_a0` to
  `expt_a3`. Check that T2, T3, T4, T8 and T9 land within about 2% of
  `expt_a3` at 1 client before attributing any delta.

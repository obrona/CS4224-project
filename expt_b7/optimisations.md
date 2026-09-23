### Prev: expt_b6

This experiment fixes how T6 expresses its reporting window. The rollup, T1's
upsert, the schema, data distribution, the other transactions and server
parameters are all unchanged from `expt_b6`. `run.sh` also records T6's plan
once after data generation.

### Motivation

`expt_b6` (job-875073) replaced T6's scan of `orders` with the
`merchant_daily_sales` rollup. Throughput fell from 405.2 TPS to 67.7 TPS at 64
clients instead of rising. T6 alone caused it:

| T6                    | `expt_b5` | `expt_b6`  |
| --------------------- | --------- | ---------- |
| Latency at 1 client   | 42.9 ms   | 184.9 ms   |
| Latency at 64 clients | 1030.2 ms | 8800.7 ms  |
| TPS, 4 to 64 clients  | 36 to 40  | 6.3 to 6.8 |

Every other transaction's 1-client latency matched `expt_b5`, T1's upsert cost
nothing measurable (19.4 vs 19.5 ms), and serialization failures went down.
T6's rate stayed flat at about 6.7/s from 4 clients up while its latency grew
in proportion to the client count, so each T6 was using most of the cluster.
At 10% of the mix, 6.7 / 0.10 = 67 TPS is the overall throughput observed.

### Why T6 got slower

`expt_b6` put the window bounds in a shared CTE:

```sql
WITH bound AS (
  SELECT CURRENT_TIMESTAMP AS now_ts,
         CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day' AS win_start
),
partial_day AS ( ... FROM orders o CROSS JOIN bound b
                     WHERE o.created_at >= b.win_start ... ),
whole_days  AS ( ... FROM merchant_daily_sales s CROSS JOIN bound b
                     WHERE s.sales_date >= ((b.win_start)::date + 1) ... )
```

`bound` is referenced twice, so it is not inlined. Citus plans it as a subplan
and ships its one row to the workers as an intermediate result. The window
predicates then become join conditions against `read_intermediate_result(...)`
rather than ranges on `idx_orders_sales_period`, and each shard scans all of
its orders.

The 1-client latency supports this. It matches `expt_b0` (198.0 ms), the last
experiment without `idx_orders_sales_period`, rather than any indexed
experiment (40.8 to 52.2 ms). No plan was captured in `expt_b6`, so this is
inferred rather than observed.

### Optimisation: inline the window bounds

`transactions/T6_global_sales.sql` writes the bounds out in each branch:

```sql
partial_day AS (
  ... WHERE o.created_at >= CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day'
        AND o.created_at <  CURRENT_TIMESTAMP
        AND o.created_at <  (CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day')::date + 1
),
whole_days AS (
  ... WHERE s.sales_date >= (CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day')::date + 1
)
```

Each predicate now compares a column with a stable expression, as the
`expt_b5` baseline did, so it can be used as an index range. The expressions
are the ones `bound` computed, and `CURRENT_TIMESTAMP` is fixed for the whole
transaction, so both branches see the same window. The correctness argument in
`expt_b6/optimisations.md` carries over unchanged.

`AS NOT MATERIALIZED` on `bound` would also force PostgreSQL to inline it, but
Citus's recursive planner makes its own decision about CTEs, so writing the
expressions out is the version that does not depend on it.

### Recording the plan

After data generation, `run.sh` writes `t6-explain.log` with an
`EXPLAIN (ANALYZE, VERBOSE, BUFFERS)` of both the new T6 and the `expt_b6`
query, kept in `diagnostics/T6_global_sales_bound_cte.sql`. Each is run once
untimed first to warm the cache. `VERBOSE` shows the SQL sent to the shards
and `ANALYZE` shows one sample shard's plan. The step runs outside the timed
benchmark, and a failure there does not stop the job.

### What to look at when this is run

- **`t6-explain.log`.** The new query should show index-only scans on
  `idx_orders_sales_period` and `idx_mds_period` and no
  `read_intermediate_result`. The `expt_b6` query should show the intermediate
  result and a full scan of `orders`, which would confirm the cause above.
- **T6 latency at 1 client**, which should come in well under `expt_b5`'s
  42.9 ms. That is the rollup's actual benefit, which `expt_b6` never measured.
- **The next bottleneck.** Recompute the latency-share table from `expt_b6`'s
  notes. T7 (14.6%) and T1 (13.6%) were the next candidates in `expt_b5`.
- **Comparability.** Run on the same nodes as `expt_b5` and `expt_b6`
  (`xcnf[16-20]`).

### Note: this experiment has not been run yet

This folder contains no `slurm-results/`.

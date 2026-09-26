### Prev: expt_a3

This experiment combines `expt_a4` (T5 routed through `order_merchant_map`)
and `expt_a5` (T6 answered from the `merchant_daily_sales` rollup) on top of
`expt_a3`. Every change in it appears in exactly one of those two experiments;
see their `optimisations.md` for each optimisation's design and why it keeps
the baseline's results. It is the A-side equivalent of `expt_b6` without
`expt_b4`'s T7 routing.

| Experiment | T5 routing | T6 rollup |
| ---------- | ---------- | --------- |
| `expt_a3`  |            |           |
| `expt_a4`  | yes        |           |
| `expt_a5`  |            | yes       |
| `expt_a6`  | yes        | yes       |

### Why the pair is run as well as each alone

Both optimisations are paid for in T1, which is 36% of workload A. After both,
T1 does its set-based statement, then inserts the `order_merchant_map` row
(usually on another worker, so the commit becomes two-phase), then upserts the
`merchant_daily_sales` row, all in one `BEGIN`/`COMMIT`:

```sql
\if :t1_order_created
INSERT INTO order_merchant_map (order_id, merchant_id)
VALUES ((:t1_new_order_id)::bigint, (:merchant_id)::bigint);

INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
VALUES (...)
ON CONFLICT (merchant_id, sales_date)
DO UPDATE SET order_count = s.order_count + 1,
              revenue     = s.revenue + EXCLUDED.revenue;
\endif
```

The rollup upsert holds its row lock until the two-phase commit that the map
write introduced completes, so the two costs can compound rather than add.
The benefits interact too: `expt_a5` alone leaves T5 capping throughput at 64
clients, so T6's improvement can only show there once `expt_a4`'s change is
also present.

The interaction is read off as
`(a6 - a3) - ((a4 - a3) + (a5 - a3))`, per transaction and per client count,
for T1 latency and overall throughput.

### What to look at when this is run

- **T1 latency at 1 client** against `expt_a3`, `expt_a4` and `expt_a5`.
- **T5 and T6 latency** against `expt_a4` and `expt_a5` respectively; each
  should match the experiment that introduced it if the two do not interfere.
- **`serialization_failures`, `pgbench_exit_code` and `failed_log_records`.**
  `expt_b6`, which has the same T1, exited with code 2 at 64 clients.
- **The next bottleneck.** Recompute the latency-share table; in `expt_b6`
  it was T1 at low client counts, which `expt_a7` targets.
- **Comparability.** Pinned to `xcnf[1,3-6]`, the same nodes as `expt_a0` to
  `expt_a5`.

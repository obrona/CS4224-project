### Prev: expt_a17

Cell of the 2^4 ablation around `expt_a17`, mirroring the workload-B ablation `expt_b27` .. `expt_b41` cell for cell: `expt_a17` with the T6 rollup switched off. Generated from `expt_a17` (on levels) and `expt_a8` (off levels); do not edit by hand. Everything else is `expt_a17`'s, including `SERIALIZABLE`, 4 shards and `WORKLOAD=A`.

| Factor | Level |
| ------ | ----- |
| T5 routing | on |
| T6 rollup | off |
| T7 routing | on |
| T1 delegated | on (`place_order`) |

### What is switched off

- **T6 rollup.** T6 is `expt_a8`'s: it aggregates the 30-day window from `orders`. There is no `merchant_daily_sales` or `idx_mds_period`: `run.sh` does not create, distribute, fill or truncate them, and T1 does not upsert the rollup.

T1 is `expt_a17`'s `place_order` with step 6 (rollup upsert) removed from the function body; nothing else in the file changes.

### What to look at when this is run

- **Comparability.** Same nodes as `expt_a17` (`xcnf[0-2,4,5]`), run concurrently with the other cells of ablation batch 1; compare with the mean of the three runs of the final design (`expt_a17`, `expt_a18`, `expt_a19`).
- **`schema-create.log` and `explain.log`.** No errors; switched-off tables and functions are absent.
- **`pgbench_exit_code`, aborted clients, retries and serialization failures** at every client count.

Run: job 979829, team id 204, on `xcnf[0-2,4,5]`, in ablation batch 1 (`expt_a22` to `expt_a29`, run concurrently).

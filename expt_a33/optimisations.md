### Prev: expt_a17

Cell of the 2^4 ablation around `expt_a17`, mirroring the workload-B ablation `expt_b27` .. `expt_b41` cell for cell: `expt_a17` with T5 routing, the T6 rollup and T1 delegation switched off. Generated from `expt_a17` (on levels) and `expt_a8` (off levels); do not edit by hand. Everything else is `expt_a17`'s, including `SERIALIZABLE`, 4 shards and `WORKLOAD=A`.

| Factor | Level |
| ------ | ----- |
| T5 routing | off |
| T6 rollup | off |
| T7 routing | on |
| T1 delegated | off (`expt_a8`'s T1) |

### What is switched off

- **T5 routing.** T5 is `expt_a8`'s: one `UPDATE orders` by `order_id`, sent to every `orders` shard. There is no `order_merchant_map` and no `next_colocated_order_id`: `run.sh` does not create, distribute, fill or truncate the map, T1 does not write it, and T1's order ids come from `benchmark_order_id_seq` directly.
- **T6 rollup.** T6 is `expt_a8`'s: it aggregates the 30-day window from `orders`. There is no `merchant_daily_sales` or `idx_mds_period`: `run.sh` does not create, distribute, fill or truncate them, and T1 does not upsert the rollup.
- **T1 delegated.** T1 is `expt_a8`'s multi-statement T1 inside `BEGIN`/`COMMIT`, sent statement by statement through the coordinator; each item's inventory `UPDATE` keeps its own `quantity >= qty` guard. `run.sh` does not create `place_order`.

### What to look at when this is run

- **Comparability.** Same nodes as `expt_a17` (`xcnf[0-2,4,5]`), run concurrently with the other cells of ablation batch 2; compare with the mean of the three runs of the final design (`expt_a17`, `expt_a18`, `expt_a19`).
- **`schema-create.log` and `explain.log`.** No errors; switched-off tables and functions are absent.
- **`pgbench_exit_code`, aborted clients, retries and serialization failures** at every client count.

Run: job 980262, team id 404, on `xcnf[0-2,4,5]`, in ablation batch 2 (`expt_a30` to `expt_a36`, run concurrently).

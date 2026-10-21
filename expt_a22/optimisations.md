### Prev: expt_a17

Cell of the 2^4 ablation around `expt_a17`, mirroring the workload-B ablation `expt_b27` .. `expt_b41` cell for cell: `expt_a17` with T5 routing switched off. Generated from `expt_a17` (on levels) and `expt_a8` (off levels); do not edit by hand. Everything else is `expt_a17`'s, including `SERIALIZABLE`, 4 shards and `WORKLOAD=A`.

| Factor | Level |
| ------ | ----- |
| T5 routing | off |
| T6 rollup | on |
| T7 routing | on |
| T1 delegated | on (`place_order`) |

### What is switched off

- **T5 routing.** T5 is `expt_a8`'s: one `UPDATE orders` by `order_id`, sent to every `orders` shard. There is no `order_merchant_map` and no `next_colocated_order_id`: `run.sh` does not create, distribute, fill or truncate the map, T1 does not write it, and T1's order ids come from `benchmark_order_id_seq` directly.

T1 is `expt_a17`'s `place_order` with step 7 (map insert) removed from the function body, `next_colocated_order_id` removed from the `\if 0` block, and the order id drawn from `benchmark_order_id_seq` (as in `expt_a16`); nothing else in the file changes.

### What to look at when this is run

- **Comparability.** Same nodes as `expt_a17` (`xcnf[0-2,4,5]`), run concurrently with the other cells of ablation batch 1; compare with the mean of the three runs of the final design (`expt_a17`, `expt_a18`, `expt_a19`).
- **`schema-create.log` and `explain.log`.** No errors; switched-off tables and functions are absent.
- **`pgbench_exit_code`, aborted clients, retries and serialization failures** at every client count.

Run: job 979828, team id 104, on `xcnf[0-2,4,5]`, in ablation batch 1 (`expt_a22` to `expt_a29`, run concurrently).

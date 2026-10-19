### Prev: expt_a17

Cell of the 2^4 ablation around `expt_a17`, mirroring the workload-B ablation `expt_b27` .. `expt_b41` cell for cell: `expt_a17` with T7 routing switched off. Generated from `expt_a17` (on levels) and `expt_a8` (off levels); do not edit by hand. Everything else is `expt_a17`'s, including `SERIALIZABLE`, 4 shards and `WORKLOAD=A`.

| Factor | Level |
| ------ | ----- |
| T5 routing | on |
| T6 rollup | on |
| T7 routing | off |
| T1 delegated | on (`place_order`) |

### What is switched off

- **T7 routing.** T7 is `expt_a8`'s: six statements by `product_id`/`inventory_id`, each sent to every `inventory` shard. There is no `product_merchant_map`: `run.sh` does not create, distribute, fill or truncate it.

### What to look at when this is run

- **Comparability.** Same nodes as `expt_a17` (`xcnf[0-2,4,5]`), run concurrently with the other cells of ablation batch 1 and its control `expt_a17_3`, a replicate of `expt_a17`; compare with that control.
- **`schema-create.log` and `explain.log`.** No errors; switched-off tables and functions are absent.
- **`pgbench_exit_code`, aborted clients, retries and serialization failures** at every client count.

Run: job 979830, team id 304, on `xcnf[0-2,4,5]`, in ablation batch 1 (`expt_a17_3` and `expt_a27` to `expt_a34`, run concurrently).

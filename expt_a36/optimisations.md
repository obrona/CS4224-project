### Prev: expt_a17

Cell of the 2^4 ablation around `expt_a17`, mirroring the workload-B ablation `expt_b27` .. `expt_b41` cell for cell: `expt_a17` with T7 routing and T1 delegation switched off. Generated from `expt_a17` (on levels) and `expt_a8` (off levels); do not edit by hand. Everything else is `expt_a17`'s, including `SERIALIZABLE`, 4 shards and `WORKLOAD=A`.

| Factor | Level |
| ------ | ----- |
| T5 routing | on |
| T6 rollup | on |
| T7 routing | off |
| T1 delegated | off (`expt_a8`'s T1) |

### What is switched off

- **T7 routing.** T7 is `expt_a8`'s: six statements by `product_id`/`inventory_id`, each sent to every `inventory` shard. There is no `product_merchant_map`: `run.sh` does not create, distribute, fill or truncate it.
- **T1 delegated.** T1 is `expt_a8`'s multi-statement T1 inside `BEGIN`/`COMMIT`, sent statement by statement through the coordinator; each item's inventory `UPDATE` keeps its own `quantity >= qty` guard. `run.sh` does not create `place_order`.

Because T5 routing and the T6 rollup are on, the original T1 also runs the `order_merchant_map` insert and then the `merchant_daily_sales` upsert (for `CURRENT_TIMESTAMP::date`, the order's day), after its final `UPDATE orders SET total_amount` and before `COMMIT`, using the same `(:order_total)::numeric(12,2)`. The original T1 never ran with these writes in the chain; they mirror steps 7 and 6 of `place_order`.

As in `expt_a17`, the original T1 draws its order id from `public.next_colocated_order_id(merchant_id)` instead of `benchmark_order_id_seq`, so the map row lands on the merchant's worker. The function's definition, verbatim from `expt_a17`, is an `\if 0` block at the end of T1, which `run.sh` extracts and runs as it does for `place_order` in `expt_a17`.

### What to look at when this is run

- **Comparability.** Same nodes as `expt_a17` (`xcnf[0-2,4,5]`), run concurrently with the other cells of ablation batch 2 and its control `expt_a17_4`, a replicate of `expt_a17`; compare with that control.
- **`schema-create.log` and `explain.log`.** No errors; switched-off tables and functions are absent.
- **`pgbench_exit_code`, aborted clients, retries and serialization failures** at every client count.

Run: job 980260, team id 204, on `xcnf[0-2,4,5]`, in ablation batch 2 (`expt_a17_4` and `expt_a35` to `expt_a41`, run concurrently).

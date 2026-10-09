# Workload-B ablation around expt_b20

`expt_b20` is the final design: `REPEATABLE READ`, 4 shards, T1 as the delegated
`place_order` function, and T7 reading one merged lookup from the reference
table `product_merchant_map`. This ablation switches four of its optimisations
off in every combination (a 2^4 factorial, 16 cells, `expt_b20` being the
all-on cell), plus two replicates of `expt_b20`.

| Factor | On (`expt_b20`) | Off |
| ------ | --------------- | --- |
| T5 routing | T5 looks up `order_merchant_map`; T1 writes it | `expt_b8`'s T5, sent to every `orders` shard; no `order_merchant_map` |
| T6 rollup | T6 reads `merchant_daily_sales`; T1 upserts it | `expt_b8`'s T6, which scans `orders`; no `merchant_daily_sales` or `idx_mds_period` |
| T7 routing | T7's merged lookup on the reference table `product_merchant_map` | `expt_b8`'s T7, six statements sent to every `inventory` shard; no `product_merchant_map`, coordinator not registered |
| T1 delegated | `place_order`, delegated to the merchant's worker | `expt_b8`'s multi-statement T1 in `BEGIN`/`COMMIT` |

When T5 routing or the T6 rollup is off, the delegated T1 drops step 7 (map
insert) or step 6 (rollup upsert) of `place_order`. When T1 delegation is off
and T5 routing or the T6 rollup is on, the original T1 gains the map insert
and/or rollup upsert just before `COMMIT`; it never ran with them in the
chain. Everything else in every cell is `expt_b20`'s, so cells one factor apart
differ only in that factor. `manifest.csv` lists each cell's levels.

## Cells

| Cells | What |
| ----- | ---- |
| `expt_b21`, `expt_b22` | replicates of `expt_b20`, identical code |
| `expt_b23` .. `expt_b26` | one factor off: T5 routing, T6 rollup, T7 routing, T1 delegation |
| `expt_b27` .. `expt_b32` | two factors off |
| `expt_b33` .. `expt_b36` | three factors off |
| `expt_b37` | all four off |

The numbers are the submission order, highest priority first, so a partly
finished chain still has the leave-one-out set.

Not rerun here, because the chain already measured them in isolation (under
`SERIALIZABLE`): the isolation level (`expt_b19` against `expt_b20`), the shard
count (`expt_b13` 32, `expt_b14` 8, `expt_b15` 4) and T7's lookup
(`expt_b15` against `expt_b17`, `expt_b18`, `expt_b19`).

## Use

```sh
python3 ablation_b20/generate.py           # (re)write expt_b21 .. expt_b37 and manifest.csv
python3 ablation_b20/generate.py --check   # verify them; exits 1 on any difference
bash ablation_b20/submit.sh                # submit all 17 as one afterany chain
```

`generate.py` builds each cell from `expt_b20` (on levels) and `expt_b8` (off
levels), and from `sources/explain/`: the three off-level explain files are
`ablation/template/explain/T{5,6,7}_*/off.sql` from `main`, and
`T1_original*.sql` plan the original T1's statements (writes without `ANALYZE`).
It refuses to overwrite a cell that already has `slurm-results/`. `--check`
also confirms that every `run.sh` is `expt_b20`'s with lines removed (apart from
the `TRUNCATE` list), and that each switched-off table appears in neither
`run.sh` nor T1.

Run the cells one at a time, as `submit.sh` does: the earlier grid
(`expt_b300` .. `expt_b347`) ran several jobs at once on the same nodes, which
made its results hard to compare.

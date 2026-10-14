# Workload-B ablation and shard-count sweep around expt_b19

`expt_b19` is the final design: `SERIALIZABLE`, 4 shards, T1 as the delegated
`place_order` function, and T7 reading one merged lookup from the reference
table `product_merchant_map`. This folder generates two sets of cells around
it:

- `expt_b27` .. `expt_b41`: a 2^4 factorial that switches four of its
  optimisations off in every combination. `expt_b19` is the all-on cell, and
  `expt_b20` and `expt_b21` already replicate it.
- `expt_b42` .. `expt_b46`: `expt_b19` with 1, 2, 8, 16 and 32 shards per
  distributed table instead of 4.

| Factor | On (`expt_b19`) | Off |
| ------ | --------------- | --- |
| T5 routing | T5 looks up `order_merchant_map`; T1 writes it | `expt_b8`'s T5, sent to every `orders` shard; no `order_merchant_map` |
| T6 rollup | T6 reads `merchant_daily_sales`; T1 upserts it | `expt_b8`'s T6, which scans `orders`; no `merchant_daily_sales` or `idx_mds_period` |
| T7 routing | T7's merged lookup on the reference table `product_merchant_map` | `expt_b8`'s T7, six statements sent to every `inventory` shard; no `product_merchant_map`, coordinator not registered |
| T1 delegated | `place_order`, delegated to the merchant's worker | `expt_b8`'s multi-statement T1 in `BEGIN`/`COMMIT` |

When T5 routing or the T6 rollup is off, the delegated T1 drops step 7 (map
insert) or step 6 (rollup upsert) of `place_order`. When T1 delegation is off
and T5 routing or the T6 rollup is on, the original T1 gains the map insert
and/or rollup upsert just before `COMMIT`; it never ran with them in the
chain. Everything else in every cell is `expt_b19`'s, so cells one factor apart
differ only in that factor. `manifest.csv` lists each cell's levels and shard
count.

An earlier version of this ablation ran around the `REPEATABLE READ` design
(now `expt_b26`) and was removed. Its cells differ from `expt_b27` ..
`expt_b41` only in `run.sh` line 70, the isolation level.

## Cells

| Cells | What |
| ----- | ---- |
| `expt_b27` .. `expt_b30` | one factor off: T5 routing, T6 rollup, T7 routing, T1 delegation |
| `expt_b31` .. `expt_b36` | two factors off |
| `expt_b37` .. `expt_b40` | three factors off |
| `expt_b41` | all four off |
| `expt_b42` .. `expt_b46` | 1, 2, 8, 16 and 32 shards |

The numbers are the submission order, highest priority first, so a partly
finished chain still has the leave-one-out set.

`expt_b13` (32 shards), `expt_b14` (8) and `expt_b15` (4) swept the shard count
before T7 was routed through the reference table. The shard cells repeat that
sweep on the final design, with 1 and 2 shards added, and change only the
`CITUS_SHARD_COUNT` default in `run.sh`. With 1 or 2 shards the
merchant-colocated tables sit on 1 or 2 of the 4 workers.

Not rerun here: the isolation level (`expt_b19` against `expt_b26`) and T7's
lookup (`expt_b15` against `expt_b17`, `expt_b18`, `expt_b19`).

## Use

```sh
python3 ablation_b19/generate.py           # (re)write expt_b27 .. expt_b46 and manifest.csv
python3 ablation_b19/generate.py --check   # verify them; exits 1 on any difference
bash ablation_b19/submit.sh                # submit all 20 as one afterany chain
bash ablation_b19/submit.sh 42 <job>       # resume from expt_b42, after job <job>
```

`generate.py` builds each ablation cell from `expt_b19` (on levels) and
`expt_b8` (off levels), and from `sources/explain/`: the three off-level explain
files are `ablation/template/explain/T{5,6,7}_*/off.sql` from `main`, and
`T1_original*.sql` plan the original T1's statements (writes without
`ANALYZE`). It refuses to overwrite a cell that already has `slurm-results/`.
`--check` also confirms that every ablation `run.sh` is `expt_b19`'s with lines
removed (apart from the `TRUNCATE` list), that each switched-off table appears
in neither `run.sh` nor T1, and that each shard cell differs from `expt_b19`
only in the `CITUS_SHARD_COUNT` line.

Run the cells one at a time, as `submit.sh` does: the earlier grid
(`expt_b300` .. `expt_b347`) ran several jobs at once on the same nodes, which
made its results hard to compare. `expt_b19` took 75 minutes, so the chain
takes about a day or longer; the 3-hour limit per job held for every cell of
the earlier `REPEATABLE READ` ablation.

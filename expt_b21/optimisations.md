### Prev: expt_b19

Replicate of `expt_b19`, the final design. `run.sh`, `transactions/` and
`explain/` are byte-identical copies of `expt_b19`'s (`SERIALIZABLE`, 4 shards,
delegated T1, T7 reading one merged lookup from the reference table
`product_merchant_map`). There is no change to the schema, data, transactions or
server parameters.

### Motivation

`expt_b19` ran once, on 2026-09-28. Same-night replicates of the earlier
`REPEATABLE READ` design agreed within about 1% at every client count, but runs
11 days apart differed by up to 5.5%, so most of the run-to-run variation comes
from running in a different period. This replicate and `expt_b20` measure that
variation for the final design, and give the alternative partitionings
(`expt_b22` .. `expt_b25`) a reference run in the same batch.

### Run and evaluation

Submit it last in the chain `expt_b20`, `expt_b22` .. `expt_b25`, `expt_b21`, so
that the batch starts and ends with the final design and any drift during the
batch shows as a difference between the two replicates. Same nodes as
`expt_b19` (`xcnf[17-21]`), run alone. Compare TPS at every client count with
`expt_b19` and `expt_b20`.

A client-count run whose data is reset before midnight and measured after it
makes T6 scan a full day of orders that is normally read from the rollup (see
`analysis/task4/ablation/README.md`). Check `benchmark.log` for such a run
before comparing.

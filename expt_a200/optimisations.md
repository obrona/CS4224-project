### Prev: expt_a100

Replicate: a second run of `expt_a100`, to measure run-to-run variation (`ablation/README.md`; levels in `ablation/manifest.csv`). `transactions/` and `explain/` are byte-identical to `expt_a100`'s.

`run.sh` is generated from `ablation/template/run.sh` with every factor off, not copied: it is `expt_a100`'s `run.sh` plus the native EXPLAIN step, so this run also records plans, which `expt_a100`'s run did not.

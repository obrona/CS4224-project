### Prev: expt_b300

Replicate: a second run of `expt_b300`, to measure run-to-run variation (`ablation/README.md`, "Workload B"; levels in `ablation/manifest_b.csv`). Renamed from `expt_b200` of the 2^5 workload-B ablation (branch `ablation-b`; bits T5R=1 T6R=2 T7R=4 DEL=8 RR=16, Citus's default 32 shards), where it replicated `expt_b100`, which is now `expt_b300`. Its result (`slurm-results/`, `citus-*.out`, `citus-*.err`) was added on that branch in d26361a; the raw logs are gzipped here (`ablation/README.md`, "Stored results").

`run.sh`, `transactions/` and `explain/` are kept as run and are byte-identical to `expt_b300`'s, including the PGPORT lines in which both differ from the generator's output (`expt_b300/optimisations.md`).

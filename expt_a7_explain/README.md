# A7 transaction plans

From the project root, submit with `sbatch expt_a7_explain/run.sh`. You can
also submit from inside `expt_a7_explain` with `sbatch run.sh`. Set `TEAM_ID`
(and any data or PostgreSQL settings) in the environment before submission
if needed; use `sbatch --export=ALL,TEAM_ID=... expt_a7_explain/run.sh` when
setting it on the command line. If submitting from another directory, export
`SCRIPT_DIR` as the absolute path to `expt_a7_explain`.

This directory contains its own five-node Citus startup, schema creation,
synthetic data generation, copied transaction SQL, and explain runner. It
creates a fresh cluster in `/tmp/<user>/citus-<job-id>` and loads the A7 data
before collecting plans for T1–T9. Citus does not support `EXPLAIN ANALYZE`
for T1's coordinator-side `INSERT ... SELECT`, so T1 gets an `EXPLAIN` plan
plus a timed execution of the same statement. T2–T9 use
`EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS)`. The cluster is stopped when
the job exits.

Results are written to `expt_a7_explain/slurm-results/job-<id>/explain-results/`:
`T1.txt` through `T9.txt` contain plans, `sql/` contains the executed SQL,
and `status.csv` reports whether each transaction succeeded. A SQL error in
one transaction is recorded while the runner continues with the others.
Each transaction uses existing representative IDs and is rolled back so the
next plan sees the generated dataset. T5 measures the `SHIPPED` branch; T7
measures both locator queries and the debit and credit statements.

The default A7 scale is large and data generation can take substantial time
and disk space. For a smaller smoke run, submit with `SCALE=0.01`.

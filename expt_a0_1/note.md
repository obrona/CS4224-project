# Workload A baseline: two worker nodes

This experiment changes the number of Citus workers from **4** in `expt_a0` to **2**. It keeps `xcnf1` as coordinator and uses `xcnf3` and `xcnf4` as workers. The baseline uses `xcnf3` through `xcnf6`. The baseline schema, transaction SQL, data scale (1), hot order percentage (50), seeds, transaction weights, and benchmark settings are unchanged.

Run from this directory on the Slurm cluster so `SLURM_SUBMIT_DIR` points here:

```bash
cd expt_a0_1
source ../.env  # create from .env.example and fill in TEAM_ID and NOTIFY_EMAIL
sbatch --mail-user="$NOTIFY_EMAIL" run.sh
```

The job writes `slurm-results/job-<job-id>/benchmark-results/summary.csv` and `transaction_metrics.csv`. Check `topology.txt` and `benchmark-results/config.txt` before comparing overall TPS and average, p50, p95, and p99 latency at each client count against `expt_a0`. Flag rows with a nonzero pgbench exit code or aborted clients.

After collecting the results, run `python3 analysis/compare_a0_parameters.py` from the repository root to refresh the comparison report and CSV.

Results: pending cluster run.

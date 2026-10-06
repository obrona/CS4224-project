# Workload A baseline: twice the synthetic data

This experiment changes `SCALE` from **1** in `expt_a0` to **2**. The expected initial row counts are 2,000 merchants, 2,000,000 customers, 1,000,000 products (and inventory rows), 10,000,000 orders, and 30,000,000 order items. The baseline schema, transaction SQL, four worker nodes, 50% hot orders among 10% hot merchants, seeds, transaction weights, and other benchmark settings are unchanged. The relative data composition stays the same.

Run from this directory on the Slurm cluster so `SLURM_SUBMIT_DIR` points here:

```bash
cd expt_a0_3
source ../.env  # create from .env.example and fill in TEAM_ID and NOTIFY_EMAIL
sbatch --mail-user="$NOTIFY_EMAIL" run.sh
```

The job writes `slurm-results/job-<job-id>/benchmark-results/summary.csv` and `transaction_metrics.csv`. Check `benchmark-results/config.txt` for `scale=2` before comparing overall TPS and average, p50, p95, and p99 latency at each client count against `expt_a0`. Flag rows with a nonzero pgbench exit code or aborted clients. This larger data load may need more time within the Slurm allocation.

After collecting the results, run `python3 analysis/compare_a0_parameters.py` from the repository root to refresh the comparison report and CSV.

Results: pending cluster run.

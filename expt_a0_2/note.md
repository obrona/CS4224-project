# Workload A baseline: stronger merchant skew

This experiment changes `HOT_ORDER_PERCENT` from **50** in `expt_a0` to **80**. Both the generated historical orders and the transactions that select a merchant use this value: 80% are directed to the hot merchant group, which remains 10% of merchants. The baseline schema, transaction SQL, four worker nodes, data scale (1), seeds, transaction weights, and other benchmark settings are unchanged.

Run from this directory on the Slurm cluster so `SLURM_SUBMIT_DIR` points here:

```bash
cd expt_a0_2
source ../.env  # create from .env.example and fill in TEAM_ID and NOTIFY_EMAIL
sbatch --mail-user="$NOTIFY_EMAIL" run.sh
```

The job writes `slurm-results/job-<job-id>/benchmark-results/summary.csv` and `transaction_metrics.csv`. Check `benchmark-results/config.txt` for `HOT_ORDER_PERCENT="80"` before comparing overall TPS and average, p50, p95, and p99 latency at each client count against `expt_a0`. Flag rows with a nonzero pgbench exit code or aborted clients.

After collecting the results, run `python3 analysis/compare_a0_parameters.py` from the repository root to refresh the comparison report and CSV.

Results: pending cluster run.

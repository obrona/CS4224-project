# Workload B baseline: half the synthetic data

This experiment changes `SCALE` from **1** to **0.5**: 500 merchants, 500,000 customers, 250,000 products (and inventory rows), 2,500,000 orders and 7,500,000 order items, with 50 hot merchants. `SCALE` is only used through `awk` in `scale_count`, so a fractional value is safe. The baseline schema, transaction SQL, seeds, transaction weights and other benchmark settings are unchanged, as are the four workers and the hot order percentage (50).

It is one of seven runs that vary one parameter of the workload-B baseline at a time, three points per parameter, all on `xcnf[17-21]` (the node set of `expt_b6` onwards) with `expt_b0_7` as the reference:

| Parameter | Values (reference in bold) | Experiments |
| --- | --- | --- |
| Workers | 2, **4**, 8 | `expt_b0_1`, `expt_b0_7`, `expt_b0_4` |
| `HOT_ORDER_PERCENT` | 10, **50**, 80 | `expt_b0_5`, `expt_b0_7`, `expt_b0_2` |
| `SCALE` | 0.5, **1**, 2 | `expt_b0_6`, `expt_b0_7`, `expt_b0_3` |

`expt_b0_1` to `expt_b0_3` make the same changes as `expt_a0_1` to `expt_a0_3` for workload A.

Run these one at a time: all seven share `xcnf17` to `xcnf19`, and none requests `--exclusive`. Run `expt_b0_7` first, since it is the reference for the other six.

Run from this directory on the Slurm cluster so `SLURM_SUBMIT_DIR` points here:

```bash
cd expt_b0_6
source ../.env  # create from .env.example and fill in TEAM_ID and NOTIFY_EMAIL
sbatch --mail-user="$NOTIFY_EMAIL" run.sh
```

The job writes `slurm-results/job-<job-id>/benchmark-results/summary.csv` and `transaction_metrics.csv`. Before comparing overall TPS and average, p50, p95 and p99 latency at each client count against `expt_b0_7`, check that `topology.txt` shows `xcnf17` as coordinator and `xcnf18` to `xcnf21` as workers and that `benchmark-results/config.txt` shows `scale=0.5`. Flag rows with a nonzero pgbench exit code or aborted clients: `expt_b0` itself lost clients at every client count from 4 up, because a serialization conflict at a distributed commit surfaces as `could not commit transaction for shard ...`, which pgbench does not retry.

Results: pending cluster run.

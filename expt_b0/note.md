# Workload B baseline: reference rerun on xcnf[17-21]

This experiment reruns the workload-B baseline unchanged on `xcnf[17-21]`; the baseline's first run (job 873005) ran on `xcnf[16-20]` and was `expt_b0` until this run replaced it (its results are in the git history). The only difference from that run is `#SBATCH --nodelist`. It is the reference for the six parameter runs below, and for comparing the final workload-B design (`expt_b12` onwards, also on `xcnf[17-21]`) against the baseline on the same hardware. Its difference from job 873005 also gives an estimate of run-to-run variation.

It is one of seven runs that vary one parameter of the workload-B baseline at a time, three points per parameter, all on `xcnf[17-21]` (the node set of `expt_b12` onwards) with `expt_b0` as the reference:

| Parameter | Values (reference in bold) | Experiments |
| --- | --- | --- |
| Workers | 2, **4**, 8 | `expt_b1`, `expt_b0`, `expt_b2` |
| `HOT_ORDER_PERCENT` | 10, **50**, 80 | `expt_b4`, `expt_b0`, `expt_b3` |
| `SCALE` | 0.5, **1**, 2 | `expt_b6`, `expt_b0`, `expt_b5` |

`expt_b1` to `expt_b6` are the same parameter study as `expt_a1` to `expt_a6` for workload A, in the same order (workers, then skew, then scale), except that `expt_b4` lowers `HOT_ORDER_PERCENT` to 10 where `expt_a4` lowers it to 20.

Run these one at a time: all seven share `xcnf17` to `xcnf19`, and none requests `--exclusive`. Run `expt_b0` first, since it is the reference for the other six.

Run from this directory on the Slurm cluster so `SLURM_SUBMIT_DIR` points here:

```bash
cd expt_b0
source ../.env  # create from .env.example and fill in TEAM_ID and NOTIFY_EMAIL
sbatch --mail-user="$NOTIFY_EMAIL" run.sh
```

The job writes `slurm-results/job-<job-id>/benchmark-results/summary.csv` and `transaction_metrics.csv`. Before comparing overall TPS and average, p50, p95 and p99 latency at each client count against job 873005, check that `topology.txt` shows `xcnf17` as coordinator and `xcnf18` to `xcnf21` as workers and that `benchmark-results/config.txt` shows the same settings as job 873005. Flag rows with a nonzero pgbench exit code or aborted clients: Job 873005 itself lost clients at every client count from 4 up, because a serialization conflict at a distributed commit surfaces as `could not commit transaction for shard ...`, which pgbench does not retry.

Results: pending cluster run.

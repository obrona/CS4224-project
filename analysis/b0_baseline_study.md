# Workload-B baseline parameter study: run facts and data-quality notes

What was run for `expt_b0_1` to `expt_b0_7`, and the problems in the data to
be aware of. Results and analysis are deliberately left out: they are in each
job's `slurm-results/job-<id>/` folder (`benchmark-results/summary.csv`,
`transaction_metrics.csv`, `result-c*.txt`, `metrics-c*/`, and the per-node
PostgreSQL logs).

## What was run

Each experiment is the provided `expt_b0` with one parameter changed. Its
`run.sh` differs from `expt_b0`'s only in that parameter and the Slurm node
list, and `transactions/` is a copy. The study runs on `xcnf[17-21]` because
`xcnf16`, `expt_b0`'s coordinator, is down (`sinfo`, 7 Oct). `expt_b0_7`
reruns `expt_b0` unchanged on those nodes as the reference.

| Parameter | Value | Experiment | Job | Nodes (coordinator first) |
| --- | --- | --- | --- | --- |
| reference | 4 workers, skew 50, scale 1 | `expt_b0_7` | 916257 | xcnf17-21 |
| workers | 2 | `expt_b0_1` | 916259 | xcnf17-19 |
| workers | 8 | `expt_b0_4` | 916261 | xcnf17-25 |
| `HOT_ORDER_PERCENT` | 80 | `expt_b0_2` | 916263 | xcnf17-21 |
| `HOT_ORDER_PERCENT` | 10 (uniform) | `expt_b0_5` | 916265 | xcnf17-21 |
| `SCALE` | 0.5 | `expt_b0_6` | 916267 | xcnf17-21 |
| `SCALE` | 2 | `expt_b0_3` | 916269 | xcnf17-21 |
| (original) | 4 workers, skew 50, scale 1 | `expt_b0` | 873005 | xcnf16-20 |

- All nodes are the same hardware: 128 CPUs and 1 TB memory each, per `sinfo`.
- Each run's `topology.txt` and `config.txt` were checked against the table,
  and the data-load logs confirm the scale (2,000 merchants at `SCALE=2`, 500
  at 0.5).
- Run settings are those of `expt_b0`: 600 s measured and 60 s warm-up per
  client count, a database reset between client counts, `SERIALIZABLE`, and
  `--max-tries=3`.
- The baseline uses Citus's default of 32 shards per table, so 16 per worker
  with 2 workers, 8 with 4, and 4 with 8.
- `expt_b0_1` to `expt_b0_3` make the same changes as `expt_a0_1` to
  `expt_a0_3` for workload A (2 workers, skew 80, scale 2). The A runs were on
  xcnf9-13, not `expt_a0`'s xcnf[1,3-6].

## Data-quality notes

### Every run lost a few clients

Every run completed, but at every client count above 1, pgbench exited with
code 2 because some clients aborted. Aborted clients per client count:

| Experiment | c1 | c4 | c8 | c16 | c32 | c64 |
| --- | --- | --- | --- | --- | --- | --- |
| `expt_b0` | 0 | 1 | 1 | 2 | 3 | 2 |
| `expt_b0_7` | 0 | 0 | 1 | 5 | 4 | 0 |
| `expt_b0_1` | 0 | 1 | 1 | 1 | 2 | 1 |
| `expt_b0_4` | 0 | 2 | 2 | 4 | 4 | 2 |
| `expt_b0_2` | 0 | 0 | 3 | 3 | 1 | 2 |
| `expt_b0_5` | 0 | 1 | 2 | 6 | 4 | 2 |
| `expt_b0_6` | 0 | 1 | 4 | 6 | 8 | 4 |
| `expt_b0_3` | 0 | 0 | 1 | 1 | 2 | 0 |

Every abort in every run is the same error:
`ERROR: could not commit transaction for shard <N> on at least one active node`
(counted from `result-c*.txt`). pgbench retries only serialization failures
and deadlocks (SQLSTATE 40001 and 40P01), so it does not retry this error and
drops the client for the rest of that client count. These points therefore ran
with fewer clients than their label for part of the run. In `expt_b0`, the
aborted clients were running T2 and T7. `expt_a0` has the same error (2
clients at c16, 1 at c32).

### `expt_b0_3` at 1 client contains long stalls

In `expt_b0_3`'s 1-client run, a few T7 transactions took 48 to 78 s (maximum
77,986 ms in `metrics-c1/T7-latency-us.txt`), while T7's median was 65 ms.
`result-c1.txt`'s progress lines show spells of 60 s and longer at 0 TPS. What
was checked: with one client there is no contention between clients, there
were no retries, the PostgreSQL logs show only trivial checkpoints, and
autovacuum barely ran. The cause was not found. No other run shows this: in
every other run's 1-client results there is no 10 s interval at 0 TPS and no
transaction slower than 6.2 s (`expt_b0_3` has 19 such intervals).

### Which run to compare against

`expt_b0` ran on xcnf16-20 and every study run on xcnf17-21, so the study runs
share hardware with `expt_b0_7`, not with `expt_b0`. The final workload-B
experiments (`expt_b6` onwards) also ran on xcnf17-21.

### Extra nodes for 8 workers

`expt_b0_4` adds xcnf22-25, which no other run used. They are the same
hardware as xcnf17-21.

### No query plans

`expt_b0`'s `run.sh` does not record `explain.log`, so none of these runs have
query plans.

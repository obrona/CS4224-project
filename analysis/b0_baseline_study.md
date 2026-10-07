# Workload-B baseline parameter study: notes for Section 4

Results of `expt_b0_1` to `expt_b0_7`, checked against their logs. Every
number below comes from the committed `summary.csv`,
`transaction_metrics.csv`, `result-c*.txt`, `topology.txt` or
`benchmark.log` of the job named. Statements that are interpretation rather
than measurement are marked as such.

## Design

Each experiment is the provided `expt_b0` with one parameter changed. Its
`run.sh` differs from `expt_b0`'s only in that parameter and the Slurm node
list, and `transactions/` is a copy. The study runs on `xcnf[17-21]` because
`xcnf16`, `expt_b0`'s coordinator, is down (`sinfo`, 7 Oct). `expt_b0_7`
reruns `expt_b0` unchanged on those nodes and is the reference.

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

All nodes are the same hardware (128 CPUs, 1 TB memory per `sinfo`). Each
`topology.txt` and `config.txt` was checked to match the table, and the data
loads confirm the scale (2,000 merchants at `SCALE=2`, 500 at 0.5). The run
settings are those of `expt_b0`: 600 s measured and 60 s warm-up per client
count, a database reset between client counts, `SERIALIZABLE`, and
`--max-tries=3`.

`expt_b0_1` to `expt_b0_3` make the same changes as `expt_a0_1` to
`expt_a0_3` for workload A (2 workers, skew 80, scale 2). The A runs were on
other nodes (xcnf9-13) than `expt_a0`, so compare the two workloads' trends,
not their absolute numbers.

## Validity: every run lost a few clients

Every run completed, but every run except at 1 client ends with pgbench exit
code 2, because some clients aborted. Aborted clients per client count:

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
`ERROR: could not commit transaction for shard <N> on at least one active node`.
Under `SERIALIZABLE`, a serialization conflict found while committing a
distributed transaction reaches pgbench as this error, not as SQLSTATE 40001,
so pgbench cannot retry it and drops the client for the rest of that client
count. In `expt_b0` the aborted scripts are T2 and T7, the two transactions that
update `inventory`. This is a property of the baseline design, not of these
runs, and it is the same in `expt_a0` (2 clients at c16, 1 at c32).

How to present it: report the counts, and treat the affected points as
measured with slightly fewer clients than labelled. Baseline throughput is flat
from 4 clients upward, so losing 1 to 8 clients changes TPS little.

## Results

Overall TPS (successful transactions over the 600 s measured run):

| Experiment | Change | c1 | c4 | c8 | c16 | c32 | c64 | Average |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `expt_b0_7` | reference | 6.68 | 7.49 | 7.68 | 7.81 | 6.28 | 6.38 | **7.05** |
| `expt_b0_1` | 2 workers | 4.65 | 4.58 | 4.84 | 4.93 | 3.69 | 3.67 | **4.39** |
| `expt_b0_4` | 8 workers | 9.04 | 12.23 | 11.79 | 12.45 | 10.08 | 10.16 | **10.96** |
| `expt_b0_2` | skew 80 | 6.68 | 7.40 | 7.49 | 7.52 | 6.18 | 5.98 | **6.88** |
| `expt_b0_5` | skew 10 | 6.73 | 7.94 | 7.73 | 7.78 | 6.35 | 6.29 | **7.14** |
| `expt_b0_6` | scale 0.5 | 10.22 | 12.26 | 10.98 | 11.21 | 9.44 | 9.24 | **10.56** |
| `expt_b0_3` | scale 2 | 2.01 | 4.28 | 4.26 | 4.53 | 3.35 | 3.36 | **3.63** |
| `expt_b0` | original, xcnf16-20 | 6.68 | 7.48 | 6.98 | 7.10 | 6.12 | 5.97 | **6.72** |

Overall latency, p50 / p99 in ms:

| Experiment | c1 | c16 |
| --- | --- | --- |
| `expt_b0_7` | 16 / 1,975 | 53 / 23,026 |
| `expt_b0_1` | 14 / 3,117 | 64 / 45,603 |
| `expt_b0_4` | 17 / 1,312 | 55 / 13,986 |
| `expt_b0_2` | 16 / 1,973 | 49 / 26,362 |
| `expt_b0_5` | 16 / 1,957 | 52 / 23,941 |
| `expt_b0_6` | 16 / 1,240 | 38 / 14,200 |
| `expt_b0_3` | 11 / 3,777 | 89 / 47,964 |

The other client counts and the per-transaction p50/p95/p99 are in each job's
`summary.csv` and `transaction_metrics.csv`.

### Run-to-run variation

`expt_b0_7` repeats `expt_b0` with only the node set changed. Their averages
differ by 4.9% (7.05 against 6.72 TPS), and their per-point TPS by at most
about 10% (c8 and c16). Differences smaller than about 5% are within this
variation and should not be claimed as effects. This is one pair of runs, so
it is a rough bound, not a measured standard deviation.

### Workers: throughput grows, but less than proportionally

2 to 4 to 8 workers gives 4.39 to 7.05 to 10.96 TPS: x1.61, then x1.55 for
each doubling. The p99 latency falls the same way (c16: 45.6 s, 23.0 s,
14.0 s).

### Skew: no measurable effect

Skew 10, 50 and 80 give 7.14, 7.05 and 6.88 TPS, all within the 5% variation.
Under the baseline, which merchant a transaction picks barely matters.

### Data size: throughput scales inversely with data

Scale 0.5, 1 and 2 give 10.56, 7.05 and 3.63 TPS: x1.50 for half the data and
x0.51 for double.

### Where the time goes: T3

T3 (Customer Order History) is 55% to 73% of total measured latency at every
client count of every run, except `expt_b0_3` at 1 client (see below), even
though it is only 5% of workload B. Its average latency at 1 client follows both trends above:

| Run | T3 at c1 |
| --- | --- |
| scale 0.5 (`expt_b0_6`) | 1,229 ms |
| reference (`expt_b0_7`) | 1,945 ms |
| scale 2 (`expt_b0_3`) | 3,602 ms |
| 2 workers (`expt_b0_1`) | 3,058 ms |
| 8 workers (`expt_b0_4`) | 1,333 ms |

The next largest shares are T4 (Product Lookup), T6 (Global Sales) and T7
(Inventory Transfer). T4 grows with clients, reaching 27% to 31% at 64
clients.

Interpretation, not measured: no query plans were recorded for these runs.
In the baseline, `orders` is distributed by `order_id` and `order_items` by
`order_item_id`, and T3 joins them on `order_id` with no `merchant_id`
condition on `order_items`. The two tables are not colocated on the join key,
so Citus has to repartition one side across the workers on every execution
(`citus.enable_repartition_joins` is on). The work grows with the size of
the tables, which fits T3 slowing roughly in proportion to `SCALE`, and it is
spread over the workers, which fits T3 speeding up with more of them. It also
explains why skew does not matter: the cost depends on total data, not on
which merchant is asked about. The plan can be confirmed by running EXPLAIN on
T3 against a baseline database. In Section 5 this is the link to `expt_b1`
and `expt_b2`, which colocate the two tables by `merchant_id` and add it to
T3's join.

## Points to treat with care

1. **`expt_b0_3` at 1 client (2.01 TPS) is out of line.** Its 4-client point is
   4.28 TPS. At c1, a few T7 transactions took 48 to 78 s (maximum 77,986 ms),
   while T7's median was 65 ms, and pgbench's progress output shows 60 s and
   longer spells of 0 TPS. With one client there is no contention, there were
   no retries, the PostgreSQL logs show only trivial checkpoints, and
   autovacuum barely ran. The cause is not known. Either report c1 with this
   caveat or leave it out of `expt_b0_3`'s average (the other five points
   average 3.96 TPS).
2. **`expt_b0` against the rest.** `expt_b0` ran on xcnf16-20, everything else
   on xcnf17-21. Compare the study runs with `expt_b0_7`, not `expt_b0`. The
   same applies when Section 5 compares the final B design (`expt_b6`
   onwards, on xcnf17-21) with the baseline: use `expt_b0_7`.
3. **8 workers uses four extra nodes** (xcnf22-25). They are the same hardware
   as xcnf17-21, but no other run used them.
4. **Shard count.** The baseline uses Citus's default of 32 shards per table:
   16 per worker with 2 workers, 8 with 4, 4 with 8. They divide evenly in all
   three runs.

## Suggested figures

- TPS against clients, one line per value, in three small panels (workers,
  skew, scale), each with `expt_b0_7` as the middle line.
- Average TPS against parameter value for workers and scale. Skew can be a
  sentence, since it has no effect.
- T3's share of latency, to show that one transaction dominates the baseline.

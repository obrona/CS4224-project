### Prev: expt_a9

This experiment tests the first step of the shard-count reduction for workload A:
8 shards per distributed table instead of the 32 used by `expt_a9`. It copies
`expt_a9`'s schema, transactions, indexes, isolation level, workload weights,
and server settings. The only intended database design change is the shard
count. The measured run used a different worker set; see Results below.
`CITUS_SHARD_COUNT` defaults to 8 and is recorded in `config.txt`; it can be
overridden to run a further sweep, including 4 shards.

### Motivation

T6 (Global Sales) is the one remaining query that must visit every shard. In
`expt_a9`, it contributes about 19% of total measured transaction time at
8 clients and 25% at 64 clients, despite being only 5% of workload A. Its
average latency grows from 26.1 ms to 314.6 ms over those client counts.
Reducing the number of shards reduces Citus task planning, dispatch, and
result-merging work for each T6 execution. The B-side 32-to-8-to-4 sweep
(`expt_b7` through `expt_b9`) found substantial gains, but workload A has a
larger T1 share, so its result must be measured independently.

### Optimisation

`create_schema` sets `citus.shard_count = 8` in the same psql session that
calls `create_distributed_table`. Each tenant-owned table remains colocated
with `merchants`. The order and product routing maps each start a separate
colocation group, as in `expt_a9`. T6 should now dispatch 8 tasks instead
of 32. Merchant-routed transactions still target their merchant's shard.

This changes the shard layout at schema creation; existing tables are not
resharded in place. The run recreates and reloads the database as before.

### Results: job 892423 versus `expt_a9` job 883120

The figures below come from each job's `benchmark-results/summary.csv` and
`transaction_metrics.csv`. Each client count was configured for 600 seconds.

| Clients | `a9` TPS | `a10` TPS | Change | `a9` p99 (ms) | `a10` p99 (ms) |
| ------- | -------: | --------: | -----: | ------------: | -------------: |
| 1       |    191.1 |     191.4 |  +0.2% |          17.0 |           15.3 |
| 4       |    765.0 |     757.6 |  -1.0% |          19.1 |           21.7 |
| 8       |   1177.6 |    1454.7 | +23.5% |          37.9 |           19.4 |
| 16      |   1056.9 |    1768.2 | +67.3% |         109.3 |           44.0 |
| 32*     |   1045.6 |    1582.7 | +51.4% |         242.2 |          113.7 |
| 64      |    966.9 |    1428.1 | +47.7% |         562.9 |          334.3 |

The peak moved from 1177.6 TPS at 8 clients to 1768.2 TPS at 16 clients.
At 8 clients, T6 average latency fell from 26.1 to 10.9 ms; at 16 clients,
from 81.2 to 20.1 ms; and at 64 clients, from 314.6 to 151.4 ms. T1 also
fell from 111.8 to 82.4 ms at 64 clients, consistent with less contention
from the all-shard query. T6's share of total measured transaction time
fell from 19.3% to 9.9% at 8 clients and from 24.6% to 17.6% at 64 clients.
The one-client result is essentially flat and the
four-client result is slightly worse: the gain appears under concurrent load.

### What the EXPLAIN logs show

The recorded T6 plan confirms the intended change: `Task Count` is 32 in
`expt_a9/slurm-results/job-883120/explain.log` and 8 in
`slurm-results/job-892423/explain.log`. In these one-off, untimed plan
captures, each shard computes local aggregates and a top 20; the coordinator
sorts the candidates. Citus receives 640 candidate rows (20 kB) from 32
shards in `a9`, versus 160 rows (5108 bytes) from 8 shards in `a10`. The
coordinator's T6 planning time falls from 5.693 to 4.185 ms and execution
time from 37.350 to 23.616 ms. The displayed worker task actually takes
longer in `a10` (5.306 versus 2.998 ms), as expected when each shard holds
more rows. It is only one task per plan, so those worker times cannot stand
for all tasks.

The other recorded routed statements remain at `Task Count: 1`, including
T1's delegated `place_order` call, T5's map lookup and update, and T7's
map lookup and inventory updates. Thus the plans support fewer T6 task
dispatches and fewer candidate rows returned to the coordinator, without a
new fan-out for those transactions. T6 is only 5% of the transaction mix,
but its long runtime under load used a disproportionate share of concurrent
client time. Less T6 work plausibly frees coordinator and worker capacity,
reduces queueing for T1 and the other transactions, and raises overall TPS.
The plans establish the task and result-size changes; the capacity and
queueing explanation is an inference from the benchmark latencies.

### Comparability and failures

`a9` ran on coordinator `xcnf1` and workers `xcnf3`-`xcnf6`; `a10` used
`xcnf1` and `xcnf2`-`xcnf5`. There is one run per configuration, so the full
TPS difference cannot be assigned to shard count alone. Most routed
transactions were slower at one client in `a10`, which also suggests changed
node or run conditions.

The asterisk in the table marks the incomplete 32-client result. All
`a9` client counts and all `a10` counts except 32 have
`pgbench_exit_code=0`. At 32 clients, `a10` reports exit code 2 and an
incomplete run: `result-c32.txt` records temporary name-resolution failures
for `xcnf2` and `xcnf3` that aborted clients. Its 1582.7 TPS is shown for
context, but is not a valid complete-run comparison. At 64 clients, failed
log records/serialization failures increased from 973 to 1595, alongside
more successful transactions (580166 to 856874); neither run records
deadlock failures.

A paired 32-versus-8-shard rerun on the same worker set would better isolate
the shard-count effect. It should also replace the incomplete 32-client
measurement. A 4-shard run on those nodes could test whether one shard per
worker helps further.

### Rerun on one node set: job 904117 versus `expt_a9r` job 904119

The results above compare different node sets, so they are not attributable.
This rerun ran `expt_a10`, `expt_a11` and `expt_a9r` (a control with
`expt_a115`'s code) concurrently on `xcnf[0-2,4,5]`, with team IDs 4, 104 and
204. From each job's `summary.csv`:

| Clients | `a9r` TPS | `a10` TPS | Change | `a9r` failed | `a10` failed |
| ------- | -------: | --------: | -----: | ----------: | ----------: |
| 1       |    181.2 |     196.2 |   +8%  |           0 |           0 |
| 4       |    701.5 |     785.3 |  +12%  |           0 |           0 |
| 8       |   1123.9 |    1376.5 |  +22%  |          13 |          10 |
| 16      |   1035.9 |    1721.9 |  +66%  |          62 |         113 |
| 32      |    988.2 |    1577.4 |  +60%  |         293 |         655 |
| 64      |    930.9 |    1461.5 |  +57%  |        1005 |        1778 |

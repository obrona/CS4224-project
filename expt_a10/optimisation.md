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

### What to measure

- Compare overall TPS at 1, 8, 32, and 64 clients with `expt_a9`, especially
  whether the drop after 8 clients improves.
- Check `explain.log` for 8 T6 tasks and one routed T1 task.
- Compare T6 latency and T1 latency. Fewer, larger shards may concentrate
  writes or change worker balance, so a T6 gain need not become a TPS gain.
- Check `failed_log_records`, retries, and `pgbench_exit_code`; a run with
  failed clients should not be treated as a valid throughput comparison.
- If 8 shards helps, repeat with `CITUS_SHARD_COUNT=4` to test one shard per
  worker on the same pinned nodes, without changing the transaction code.

### Results: job 890809 versus `expt_a9` job 883120

Both jobs completed 600-second measurements at each client count with
`pgbench_exit_code=0`. Throughput and latency below come from each job's
`benchmark-results/summary.csv` and `transaction_metrics.csv`.

| Clients | `a9` TPS | `a10` TPS | TPS change | `a9` p99 (ms) | `a10` p99 (ms) |
| ------- | -------: | --------: | ---------: | ------------: | -------------: |
| 1       |    191.1 |     191.1 |      +0.0% |          17.0 |           15.2 |
| 4       |    765.0 |     811.1 |      +6.0% |          19.1 |           14.9 |
| 8       |   1177.6 |    1487.1 |     +26.3% |          37.9 |           19.1 |
| 16      |   1056.9 |    1862.2 |     +76.2% |         109.3 |           41.9 |
| 32      |   1045.6 |    1601.9 |     +53.2% |         242.2 |          132.5 |
| 64      |    966.9 |    1462.1 |     +51.2% |         562.9 |          332.3 |

The peak moved from 1177.6 TPS at 8 clients to 1862.2 TPS at 16 clients.
T6's average latency fell from 26.1 to 10.6 ms at 8 clients (-59.3%) and
from 314.6 to 148.2 ms at 64 clients (-52.9%). T6's share of total measured
transaction time fell from 19.3% to 9.9% at 8 clients and from 24.6% to
17.7% at 64 clients. T1 remains the largest contributor: about 68.1% at
64 clients in `a10`. Its average latency fell from 111.8 to 80.1 ms there.

The likely mechanism is less planning, dispatch, and merging for T6's
all-shard query, which also leaves more capacity for concurrent transactions.
This is an inference from the timings: `a10` did not capture a plan confirming
the task count. Its `explain.log` reports that `expt_a10/explain/T*.sql` was
missing. Plan capture runs outside the timed benchmark and did not stop it.

The runs do not isolate shard count. `a9` used workers `xcnf3` through
`xcnf6`, whereas `a10` used `xcnf2` through `xcnf5`, according to their
`topology.txt` files. The one-client latencies for most routed transactions
were 5-17% higher in `a10`, so node or run conditions may have differed.
There is one run per configuration, with no estimate of run-to-run variance.
At 64 clients, failed log records/serialization failures rose from 973 to
1742, alongside a larger number of successful transactions (580166 to
877284); neither run recorded deadlock failures.

Rerun both shard counts on the same pinned nodes, include the `explain/`
scripts, and verify T6's task count before attributing the full TPS difference
to shard reduction. A subsequent 4-shard run can test whether reducing the
count further helps.

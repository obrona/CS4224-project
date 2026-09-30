### Prev: expt_a9

This experiment tests the first step of the shard-count reduction for workload A:
8 shards per distributed table instead of the 32 used by `expt_a9`. It copies
`expt_a9`'s schema, transactions, indexes, isolation level, workload weights,
node list, and server settings. The only design change is the shard count.
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

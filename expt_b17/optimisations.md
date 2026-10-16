### Prev: expt_b15

This experiment makes `product_merchant_map`, T7's product-to-merchant lookup
table, a reference table, and registers the coordinator in Citus's metadata
so that it holds a copy. T7's two lookups then read the coordinator's local
copy instead of going to a worker. It builds on `expt_b15`, not `expt_b16`:
T7's transfer is `expt_b15`'s again, run by the coordinator. There is no other
change to the schema, data distribution (4 shards), indexes, transactions or
server parameters.

### Motivation

In `expt_b15` (job-883179) T7 is the largest share of latency at every client
count: 36.2% at 1 client, 37.0% at 8 and 45.6% at 64. It takes 4.6 ms at 1
client although its work on the shards is tiny: in `explain.log` each of its
statements executes in 0.09 to 0.20 ms on the shard but takes 1.1 to 1.7 ms
end to end. Its routed path sends 6 statements one after another: two map
lookups, `BEGIN`, the debit, the credit and `COMMIT`.

`expt_b16` (job-884062) moved the transfer part into a distributed function,
delegated to the source merchant's worker. It regressed, from 3897.1 to
2672.9 TPS at 64 clients. T7's latency split into two groups: about a quarter
of transfers, where both merchants are on the same worker, took 2 to 3.5 ms,
faster than `expt_b15`; the rest took 8 to 12 ms. Citus does not cache the
connections opened by a backend that serves a connection from another node,
which is the kind of backend a delegated call runs in
(`ShouldShutdownConnection` in `connection_management.c`). So every transfer
whose destination is on another worker opened a new connection there and
closed it at the end. That change is therefore not carried forward.

This experiment leaves the transfer to the coordinator, whose connections are
cached, and targets the other part of T7: the two lookups.

### Optimisation: product_merchant_map as a reference table

```sql
SELECT citus_set_coordinator_host('<coordinator>', <port>);  -- before the workers are added
...
SELECT create_reference_table('product_merchant_map');       -- was create_distributed_table(..., 'product_id')
```

A reference table has one shard, with a full copy on every node in Citus's
metadata. The coordinator was not in the metadata until now (`pg_dist_node`
listed only the 4 workers), so `run.sh` registers it with
`citus_set_coordinator_host` before adding the workers. It receives no shards
of distributed tables, because `shouldhaveshards` defaults to `false` for the
coordinator.

With a copy on the coordinator, Citus runs each lookup locally there, with no
network hop: a query with a single task that has a copy on the node running
it is executed in that session (`ShouldExecuteTasksLocally` in
`local_executor.c`). That removes 2 of the 6 network hops in a transfer
between two workers (2 lookups, debit, credit, prepare, commit), and 2 of 5
when both merchants are on the same worker. The coordinator still handles the
same 6 statements, so the saving is the wait on the network and the work of
sending and receiving, not the planning.

T7's statements do not change. Only the comment above the lookups changes.

### Why a reference table fits this table

Every write to a reference table has to reach every copy, inside the writing
transaction. That is only cheap for a table that is rarely written:

- **`product_merchant_map` is never written during the benchmark.**
  `generate_data` fills it once from `products`. No transaction creates
  products or moves one to another merchant; T9 only changes the price. So
  the copies cost nothing while the benchmark runs. Loading writes its
  500,000 rows to 5 nodes instead of 1, outside the timed runs.
- **`order_merchant_map` stays sharded by `order_id`.** T1 inserts a row for
  every order, so as a reference table every T1 would write to all 5 nodes
  with a two-phase commit.

Size is not a concern: 500,000 rows of two `bigint`s is a few tens of MB per
node.

### Why T7 still behaves like expt_b0

The lookups read the same rows with the same statements, so they return the
same merchant ids. Citus writes to every copy of a reference table in the
same transaction, and the table is only written while loading, so every copy
is complete and identical before the benchmark starts. The lookups ran
outside the transfer's transaction in `expt_b15` too, and the map never
changes, so it does not matter which copy answers. The transfer itself is
`expt_b15`'s, unchanged.

### What could get worse

- **Coordinator CPU.** The lookups' index reads now run on the coordinator,
  which `expt_b16` showed to be a bottleneck at high client counts. The reads
  are single-row primary-key lookups, and the coordinator no longer sends
  them to a worker or waits for a reply, so the net effect should be small,
  but it is the thing to watch.
- **Load time.** The map is written to 5 nodes on every reload, which adds
  a few seconds to each `reset_benchmark_database`.

### Results (job-951148)

This run replaces the first one, job-885153. In that run the transactions
that never read the map (T2, T4, T8, T9) were about 20% faster than in
`expt_b15` at 1 client and 15 to 27% slower at 64, so its conditions differed
from `expt_b15`'s. This run is on the same nodes as `expt_b15`
(`xcnf[17-21]`).

`schema-create.log` lists the coordinator, xcnf17, in `pg_dist_node` with the
four workers. In `explain.log` T7's lookup is one task on xcnf17, the
coordinator's own copy of the map, and its index scan takes 0.04 ms. The log
has no `executing the command locally` NOTICE, as this experiment's explain
file does not turn on `citus.log_local_commands`, so it does not by itself
prove that the lookup ran locally. The lookup is not run before the EXPLAIN,
so its 4.5 ms total is the session's first read of the map.

| Clients | `expt_b15` TPS | `expt_b17` TPS | Change | T7 avg, `expt_b15` | T7 avg, `expt_b17` |
| ------- | -------------- | -------------- | ------ | ------------------ | ------------------ |
| 1       | 263.1          | 272.8          | +3.7%  | 4.59 ms            | 4.03 ms            |
| 4       | 1187.7         | 1286.1         | +8.3%  | 3.53 ms            | 2.79 ms            |
| 8       | 2642.1         | 2728.9         | +3.3%  | 3.73 ms            | 3.21 ms            |
| 16      | 3386.2         | 3493.6         | +3.2%  | 6.59 ms            | 5.82 ms            |
| 32      | 3792.3         | 3864.3         | +1.9%  | 12.45 ms           | 11.35 ms           |
| 64      | 3897.1         | 3931.0         | +0.9%  | 24.93 ms           | 23.14 ms           |

- **Throughput is above `expt_b15` at every client count**, and the gain
  shrinks as clients increase, from 3.7% at 1 client (8.3% at 4) to 0.9% at
  64.
- **T7 is 7 to 21% faster.** At 1 client it falls by 0.56 ms, from 4.59 to
  4.03 ms (p50 4.78 to 4.15 ms, p95 5.33 to 4.67 ms). That is less than two
  network hops: in `expt_b15` each of T7's statements takes 1.1 to 1.7 ms end
  to end. The lookups are still two separate statements from pgbench to the
  coordinator, so local execution likely saves only the coordinator-to-worker
  part of each.
- **The transactions that never read the map are slower than in
  `expt_b15`.** T2, T4, T8 and T9 are 3 to 4% slower at 1 and 8 clients, 5 to
  6% at 16, 6 to 8% at 32 and 7 to 9% at 64; only at 4 clients are they about
  3% faster. That growth with client count fits the coordinator CPU cost
  listed under "What could get worse". `expt_b19`, which also reads the map on
  the coordinator, has the same transactions up to 6% slower than `expt_b15`,
  and `expt_b18`, which does not, within 5%. But this run is 19 days after
  `expt_b15` (2026-10-15 against 2026-09-26), and runs 11 days apart have
  differed by up to 5.5% (`expt_b20`), so part or all of it may come from
  running in a different period.
- **Retries are about the same** at 64 clients: 6154 retried transactions
  against 5996, and 68 serialization failures against 83.
- **Against `expt_b18` and `expt_b19`**, this run is 0.3 to 3.2% above
  `expt_b18` and 1.8 to 2.7% below `expt_b19` at every client count. Both ran
  on 2026-09-28, so these gaps are within the variation between periods.

`expt_b19` combines this reference table with `expt_b18`'s merged lookup.

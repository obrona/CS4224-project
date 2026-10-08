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

### Optimisation: one lookup statement instead of two

```sql
SELECT COALESCE(MAX(merchant_id) FILTER (WHERE product_id = :source_product_id), 0) AS source_merchant_id,
       COALESCE(MAX(merchant_id) FILTER (WHERE product_id = :dest_product_id), 0)   AS dest_merchant_id
FROM product_merchant_map
WHERE product_id IN (:source_product_id, :dest_product_id)
```

The first run of this experiment (job-885153) kept `expt_b15`'s two lookup
statements. T7 at 1 client fell from 4.6 to 3.0 ms, but throughput fell at
8 clients and above (3897.1 to 3820.1 TPS at 64), and the single-shard
transactions that never read the map (T2, T4, T5, T8, T9) got about 1 ms
slower at 64 clients. The likely cause is coordinator CPU: each lookup is
now planned and executed on the coordinator (the shard query's own planning
alone took 0.46 ms in `explain.log`), which was already the bottleneck.

Merging the two lookups halves that work: pgbench sends one statement
instead of two, and the coordinator plans and executes the shard query once,
with two index searches. The result is unchanged: a missing product still
gives 0, and when both ids are equal both columns get the same merchant, which
the existing `source_product_id = dest_product_id` check still rejects. Both
ids are now read in the same snapshot.

The debit and credit do not change.

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

### What to look at when this is run

- **`schema-create.log`.** `pg_dist_node`, printed by T1's function block,
  now also lists the coordinator.
- **`explain.log`.** T7's lookup plan should show its task on the coordinator
  itself (local execution), not on an `xcnf` worker. If it still goes to a
  worker, the reference table is not being read locally and this experiment
  saves nothing. The plan names the coordinator as the node either way, so
  the explain file turns on `citus.log_local_commands` around it: a NOTICE
  `executing the command locally` confirms local execution. The lookup runs
  once before the EXPLAIN, so its timing is not that of a cold session (in
  job-885153 it was the session's first read of the map and took 5.1 ms).
- **T7 latency at 1 client**, 4.6 ms in `expt_b15`. Its two groups (same
  worker and different workers) should both shift down by roughly the cost
  of two network hops.
- **Throughput at 32 and 64 clients**, 3792.3 and 3897.1 TPS in `expt_b15`.
- **The other transactions** should be unchanged; only T7 reads the map.
- **Comparability.** Run on the same nodes as `expt_b15` (`xcnf[17-21]`).

### Note: this experiment has not been run yet

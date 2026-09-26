### Prev: expt_b7

This experiment creates every distributed table with 8 shards instead of
Citus's default of 32, i.e. 2 per worker instead of 8. There is no change to
the schema, indexes, transactions, or other server parameters carried over from
`expt_b7`.

The count is set by a new `run.sh` variable, `CITUS_SHARD_COUNT` (default 8),
which `create_schema` applies with `SET citus.shard_count` before creating the
tables. It is recorded in `config.txt`. The server-wide default is unchanged.

### Motivation

Each transaction's share of total measured latency in `expt_b7`
(`avg_latency_ms` x `successful_transactions`, over the workload total):

| Transaction            | Share at 1 client | Share at 8 clients | Share at 64 clients |
| ---------------------- | ----------------- | ------------------ | ------------------- |
| T6 Global Sales        | 39%               | 44%                | 51%                 |
| T7 Inventory Transfer  | 29%               | 26%                | 23%                 |
| T1 Place Order         | 21%               | 20%                | 17%                 |
| T5 Update Order Status | 3%                | 3%                 | 2%                  |

T6 is the largest share at every client count. It is also the only transaction
that still runs on every shard: all the others were routed to one or two shards
by `expt_b1` to `expt_b5`.

### Why T6 is slow

`expt_b7`'s `explain.log` shows T6 as 32 tasks. The sampled task spends
1.3 ms planning and 2.6 ms executing on its worker, and the whole statement
takes 31 ms on the coordinator. The data T6 actually needs is small: since
`expt_b6` it reads about 30,000 rollup rows plus the boundary day's orders, so
under 1,000 rows per shard. Most of the cost is paying the per-task overhead
32 times over: planning, the executor, a connection round trip, and merging
the results on the coordinator. With 4 workers and
`citus.max_adaptive_executor_pool_size = 4`, each worker also runs its 8 tasks
in two waves.

Cutting the number of shards cuts that overhead directly.

### Optimisation: 8 shards instead of 32

```sql
SET citus.shard_count = 8;   -- read by every create_distributed_table in create_schema
```

For T6 this means 8 tasks instead of 32, each over 4 times as much data, and
one wave per worker instead of two.

Routed transactions (T1 to T5, T7 to T9) run on one shard, or two for T7,
whatever the shard count. Fewer, larger shards change only how many rows each
per-shard index covers, which adds at most one level to a B-tree. Row locks,
and so contention on hot merchants, are per row, not per shard.

What could get worse:

- **Load balance.** With 2 shards per worker, the 100 hot merchants (50% of
  order activity) hash into 8 buckets instead of 32. That is still about 12 hot
  merchants per shard, but the split across workers is lumpier.
- **Cross-worker T7.** This depends on which worker, not which shard, so it is
  unchanged at 3 in 4 transfers.
- **The two lookup maps** (`product_merchant_map`, `order_merchant_map`) also
  drop to 8 shards. Every access to them is routed, so this should not matter.

### Local evidence before running

These numbers come from a Citus 14.1.0 docker cluster on one machine, with a
coordinator and 2 workers and the full-scale dataset (1,000 merchants, 5M
orders). They are a proxy, not a result: all three containers share one CPU,
so network costs are near zero and CPU contention is exaggerated.

T6 alone, `expt_b7`'s query:

| Shards | c1 TPS | c8 TPS |
| ------ | ------ | ------ |
| 32     | 80.5   | 129.3  |
| 8      | 168.2  | 606.2  |
| 4      | 205.3  | 978.4  |

The full workload B mix with `expt_b7`'s transactions, 30 s per point:

| Clients | 32 shards | 4 shards (2 per worker) | Change |
| ------- | --------- | ----------------------- | ------ |
| 1       | 156.0     | 173.0                   | +11%   |
| 8       | 626.2     | 679.8                   | +9%    |
| 16      | 987.2     | 1211.9                  | +23%   |

There were no failed transactions at either shard count. Function delegation
for T1 was checked after resharding: it is still one task on one worker.

### An idea that did not work: running totals for T6

This experiment was first designed around a different change. The estimate
behind it: from `expt_b7`'s `explain.log`, each T6 shard task spends about
2.2 ms aggregating around 940 rollup rows. At 124 T6/s that is about 60% of
the workers' CPU at 64 clients. The plan was to replace `merchant_daily_sales`
with per-merchant running totals, so that T6 reads 2 rows per merchant (about
2,000 index probes) instead of summing 30 (about 30,000 rows).

It was built and checked for exactness against the baseline query. It
returned identical results for windows from 0 to 1,000 days, and its totals
matched a recomputation from `orders` after concurrent T1 load. It was then
dropped, because at full scale it did not help:

- Summed over all 32 tasks, both versions do about the same shard work:
  12 to 15 ms per T6.
- T6-only throughput was lower: 66 against 81 TPS at c1, 103 against 129 TPS
  at c8.

The 2.2 ms in `expt_b7`'s `explain.log` was an artefact of when the plan was
recorded. `explain.log` is written straight after data generation, which runs
`ANALYZE` but not `VACUUM`, so the visibility map is not yet set and the rollup
is read with a Bitmap Heap Scan that visits the heap (1.76 ms). Once vacuumed,
it is an index-only scan at about 0.56 ms, and summing 30 small rows per
merchant is already about as cheap as 2 index probes. The per-task overhead
around that work was what actually cost time, and that is what this
experiment targets.

### What to look at when this is run

- **Comparability.** Run on the same nodes as `expt_b7` (`xcnf[17-21]`).
- **`schema-create.log`.** `create_distributed_function` succeeds and every
  worker shows `hasmetadata` and `metadatasynced` as `t`.
- **`explain.log`.** T6 shows `Task Count: 8`. T1's call is still one `Task`
  whose query is the call itself.
- **T6 latency.** 18.8 ms at 1 client and 263.3 ms at 64 in `expt_b7`.
- **Everything else within noise at 1 client.** T1, T2, T4, T5, T7, T8 and T9
  are routed and should not move. A clear regression there would point to
  load imbalance or contention, not to T6.
- **`serialization_failures`**, 19 at 64 clients in `expt_b7`. Larger shards
  should not change row-level conflicts.
- **Follow-up.** If 8 helps, 4 (one shard per worker) is the natural next
  point: `CITUS_SHARD_COUNT=4`.

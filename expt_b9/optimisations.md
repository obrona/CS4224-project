### Prev: expt_b8

This experiment sets `CITUS_SHARD_COUNT` to 4, one shard per worker, instead of
`expt_b8`'s 8. Nothing else changes: `run.sh` differs from `expt_b8`'s only in
that default, and `transactions/` and `explain/` are identical.

`expt_b7` (32 shards), `expt_b8` (8) and `expt_b9` (4) form a sweep of
throughput against shard count. The reasoning for reducing the shard count is
in `expt_b8/optimisations.md`. In short, T6 is the largest latency share and
the only transaction that still runs on every shard. Its work per shard is
under a millisecond, so its cost is mostly per-task overhead, paid once per
shard.

### Why go to one shard per worker

- **T6 runs one task per worker.** With `citus.max_adaptive_executor_pool_size = 4`,
  each worker handles its part of T6 in a single task on a single connection.
- **Local evidence favours it.** On a Citus 14.1.0 docker cluster (coordinator
  and 2 workers on one machine, full-scale data), T6 alone at 8 clients ran at
  129 TPS with 16 shards per worker, 606 with 4, and 978 with 2. The full B
  mix at 2 per worker was 9% to 23% above 16 per worker. One shard per worker
  was not run as a full mix. See `expt_b8/optimisations.md` for the
  limitations of that setup.
- **Load balance is the best of the three.** Citus's hash placement puts the
  100 hot merchants (50% of order activity) onto workers as follows,
  computed from `worker_hash` and checked against real placements for 32 and
  8 shards on a 4-worker cluster:

  | Shards | Hot merchants per worker | Share of orders per worker     |
  | ------ | ------------------------ | ------------------------------ |
  | 32     | 34 / 21 / 20 / 25        | 28.9% / 22.6% / 22.0% / 26.4%  |
  | 8      | 24 / 23 / 20 / 33        | 23.9% / 23.9% / 22.4% / 29.8%  |
  | 4      | 24 / 25 / 23 / 28        | 24.4% / 25.7% / 23.4% / 26.4%  |

  An even split would be 25% each.

### What could get worse

- **T6's parallelism within a worker.** One T6 now uses one CPU per worker
  instead of up to 4. This matters only at low client counts, where other
  clients do not fill the idle CPUs. Watch T6 at c1 against `expt_b8`.
- **All of a worker's writes go to one table per relation.** Every T1 appends
  to the end of the same `created_at` index on the worker's single `orders`
  shard, and extends the same heap files. At about 124 orders/s cluster-wide
  in `expt_b7` this should be far from contended, but it is the most
  concentrated layout. Watch T1 and T5 latency at c32 and c64.
- **Scaling.** With 4 shards the colocation group cannot use more than 4
  workers without resharding. It is irrelevant here, but it is the cost of
  this layout on a growing cluster.

### What to look at when this is run

- **Comparability.** Run on the same nodes as `expt_b7` and `expt_b8`
  (`xcnf[17-21]`), and not at the same time as `expt_b8`: both are pinned to
  those nodes and neither job is exclusive.
- **`explain.log`.** T6 shows `Task Count: 4`, one task on each worker.
- **The sweep.** Plot overall TPS against shard count (32, 8, 4) at each
  client count, and T6 latency beside it. If 4 is below 8 at low client
  counts but above it at high ones, lost intra-worker parallelism is the
  likely reason.
- **`serialization_failures` and `deadlock_failures`**, compared with
  `expt_b7` and `expt_b8`.

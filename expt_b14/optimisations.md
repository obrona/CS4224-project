### Prev: expt_b13

This experiment lowers the isolation level on every node from `SERIALIZABLE`
to `REPEATABLE READ` (`PG_ISOLATION_LEVEL` in `run.sh`, written to each
node's `default_transaction_isolation`). Nothing else changes: the
transactions, schema, data distribution and indexes are `expt_b13`'s.

### Motivation

`expt_b13` (job-886110) is the best result so far, 4020.7 TPS at 64 clients.
As throughput rose, more transactions were retried: at 64 clients 7649
transactions needed a retry and 141 still failed after 3 tries, against 5996
and 83 in `expt_b9`. Almost all of them are T1: 3.1% of T1s at 64 clients
were retried, against at most 0.03% of any other transaction.

The workers' PostgreSQL logs from job-886110 show which conflicts cause
them. Over the whole job (every client count and warmup):

| Error                                                       | Count  |
| ----------------------------------------------------------- | ------ |
| `could not serialize access due to concurrent update`       | 18,140 |
| `could not serialize access due to read/write dependencies` | 488    |

The first is a write-write conflict: a transaction tried to change a row
that a concurrent transaction changed after it took its snapshot. The second
comes only from `SERIALIZABLE`'s conflict detection (serializable snapshot
isolation, SSI). Of the write-write conflicts, 17,216 (95%) are T1's upsert of
`merchant_daily_sales`: every order for a hot merchant updates that merchant's
row for today. The rest are updates of `inventory` rows by T1 (431), T7 (397)
and T2 (94).

### What REPEATABLE READ changes

In PostgreSQL, `REPEATABLE READ` is snapshot isolation. Like `SERIALIZABLE`,
each transaction reads from one snapshot taken at its first statement, and a
transaction that updates or locks a row changed by a concurrent transaction
fails with `could not serialize access due to concurrent update`, which
pgbench retries. What it drops is SSI:

- **No read tracking.** `SERIALIZABLE` records a predicate lock for every row
  and index range each transaction reads, and checks every write against
  them. T6 alone reads about 8,000 rollup rows per shard task.
- **No read/write-dependency aborts.** The 488 errors of the second kind
  disappear.

It does not remove the write-write conflicts, which are 97% of the errors.
T1's hot rollup row conflicts exactly as before. The expected gain is
therefore small: the cost of SSI's bookkeeping, and the retries of 2.6% of
conflicts.

Citus follows the setting everywhere. Each transaction Citus opens on a
worker starts with `BEGIN TRANSACTION ISOLATION LEVEL` and the coordinator's
level (`BeginTransactionCommand` in `remote_transaction.c`). T1's delegated
call runs in the worker's own transaction, at that worker's
`default_transaction_isolation`, which `run.sh` sets on every node.

### Why the transactions still behave like expt_b0

The only anomaly `REPEATABLE READ` allows that `SERIALIZABLE` prevents is
write skew: two concurrent transactions read overlapping data, each writes a
different row based on what it read, and together they break a rule that
each alone keeps. None of the nine transactions can do this:

- **T1** reads inventory rows in its stock check and then updates those same
  rows. A concurrent change to any of them makes the update fail with a
  serialization error, and the retry sees the new quantity. Stock cannot be
  over-reserved. It also reads the customer and product prices, which it does
  not write; T8 and T9, which write them, read nothing T1 writes, so the
  outcome is that of T1 running before them. The rollup upsert and the other
  inserts write rows no other transaction reads to make a decision.
- **T2, T8, T9** are each one `UPDATE`, and so is T5's write. Each reads and
  writes the same row, so a concurrent change to it is a write-write
  conflict, which is still detected. T5's lookup, a separate statement as
  before, reads `order_merchant_map`, whose rows never change once T1 has
  inserted them.
- **T7** debits and credits the rows it reads, so the same holds. Its
  lookups read `product_merchant_map`, which nothing writes during the run.
- **T3, T4, T6** are single read-only statements. T6's exactness argument in
  `expt_b6/optimisations.md` needs only that one snapshot sees an order and
  its rollup row together, which holds because T1 writes both in one
  transaction on one shard.

Citus gives no single snapshot across nodes at any isolation level, so
nothing that crosses shards changes either.

### What to look at when this is run

- **Errors.** `serialization_failures` and `retried_transactions` at 32 and
  64 clients, 23/4294 and 141/7649 in `expt_b13`. Expect a small drop, not
  their disappearance. The workers' logs should contain no `read/write
dependencies` errors at all, and about as many `concurrent update` errors.
- **Throughput and latency** at every client count against `expt_b13`
  (279.5 TPS at 1 client, 4020.7 at 64). If `REPEATABLE READ` helps, it should
  be mostly T6 (the largest reader) and T1.
- **`failed_log_records`** should stay as in `expt_b13`: no new kind of error
  appears.
- **Comparability.** Run on the same nodes as `expt_b13` (`xcnf[17-21]`).
  T2, T4, T8 and T9 barely depend on the isolation level, so large changes in
  their latency would point to different conditions on the nodes rather than
  to this change.

### Note: this experiment has not been run yet

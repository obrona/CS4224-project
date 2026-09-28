### Prev: expt_b13

This experiment lowers the isolation level on every node from `SERIALIZABLE`
to `READ COMMITTED` (`PG_ISOLATION_LEVEL` in `run.sh`), and makes the one
change to T1 that `READ COMMITTED` needs for T1 to stay correct: its stock
check locks each inventory row with `FOR UPDATE OF i`. Nothing else changes
from `expt_b13`.

### Motivation

`expt_b13` (job-886110) reached 4020.7 TPS at 64 clients, with 7649 retried
transactions and 141 serialization failures there, almost all of them T1
(3.1% of T1s retried). The workers' logs show 18,140 `could not serialize
access due to concurrent update` errors over the job, against 488 from
`SERIALIZABLE`'s read/write-dependency checks. 95% of the write-write
conflicts are T1's upsert of the hot merchant's `merchant_daily_sales` row
for today. See `expt_b14/optimisations.md` for the breakdown.

`REPEATABLE READ` still raises write-write conflicts. `READ COMMITTED` does
not raise them at all.

### What READ COMMITTED changes

- **Each statement sees the data committed when it starts**, not a snapshot
  from the start of the transaction.
- **Conflicting writes wait instead of failing.** An `UPDATE`, `SELECT ...
FOR UPDATE` or `INSERT ... ON CONFLICT DO UPDATE` that finds its row changed
  by a concurrent transaction waits for that transaction to finish, then
  applies to the latest version of the row, re-checking its `WHERE`
  condition against it.
- **No serialization errors.** Only deadlocks are still reported and retried
  by pgbench.

So a T1 that meets a busy rollup row now waits for the other T1 to commit and
then adds its order to the updated row. Under `SERIALIZABLE` it waited just
as long, then failed and pgbench reran the whole script: a new id draw, the
delegated call and every statement in `place_order` again.

Citus follows the setting everywhere, as described in
`expt_b14/optimisations.md`.

### The change to T1

T1's stock check (step 2 of `place_order`) and its decrement (step 3) are
separate statements. Step 3 has no `quantity >= needed` condition of its
own; it relies on step 2 having checked. Under `SERIALIZABLE` and
`REPEATABLE READ` that is safe, because step 3 fails if the row changed after
the snapshot. Under `READ COMMITTED` without a change:

| Step                     | T1-A (needs 3)        | T1-B (needs 3)                                                 |
| ------------------------ | --------------------- | -------------------------------------------------------------- |
| stock check (quantity 5) | 5 >= 3, passes        | 5 >= 3, passes                                                 |
| decrement                | 5 - 3 = 2, row locked | waits for A                                                    |
| A commits                |                       | re-reads the row: 2 - 3 = -1, violates `CHECK (quantity >= 0)` |

The constraint stops the stock going negative, but B ends with an error that
pgbench does not retry and that by default ends that client's run.
`expt_b0` would have rejected B's order cleanly, as out of stock.

The fix is one clause on the stock check:

```sql
SELECT i.quantity, p.price
INTO v_stock, v_price
FROM public.inventory i
JOIN public.products p ON p.merchant_id = p_merchant_id AND p.product_id = i.product_id
WHERE i.merchant_id = p_merchant_id AND i.product_id = r.product_id
FOR UPDATE OF i;
```

`FOR UPDATE OF i` locks the inventory row as it is checked and keeps it
locked until commit. If another transaction holds it, the check waits and
then reads the latest committed quantity. In the example, B's check now
waits for A, sees 2, and returns `false` before writing anything: the same
outcome as `expt_b0`. The quantity checked is always the one step 3
decrements, because nobody else can change the row in between. Only the
inventory row is locked, not the product row, so T9's price updates are not
blocked.

The loop visits products in `product_id` order, so two T1s lock shared rows
in the same order and cannot deadlock with each other.

### Why the transactions still behave like expt_b0

- **T1.** The stock check locks what it checks (above). Each product's price
  is read once and used for both its item row and the order total, so an
  order is internally consistent. Different products' prices may be read at
  slightly different moments, but each T9 changes one product, so the result
  is as if the T9s that committed before T1 read a product ran before T1 and
  the rest after. The rollup upsert waits for any concurrent upsert of the
  same row and adds to the latest version, so no order is lost from the
  rollup. The order, items, rollup and map row still commit or roll back
  together.
- **T2.** One `UPDATE ... WHERE quantity + change >= 0`. The condition is
  re-checked against the latest row after any wait.
- **T3, T4.** One read-only statement each, on one shard.
- **T5.** The lookup reads `order_merchant_map`, whose rows never change once
  written. The `UPDATE ... IS DISTINCT FROM` is re-checked after any wait.
- **T6.** One read-only statement. On each shard it reads `orders` and
  `merchant_daily_sales` from one snapshot, which sees an order and its rollup
  change together, as the exactness argument in `expt_b6/optimisations.md`
  requires.
- **T7.** The debit's `quantity >= qty` is part of its `UPDATE` and is
  re-checked after any wait, so stock never goes negative. The credit adds to
  the latest quantity. The lookups read a table nothing writes.
- **T8, T9.** One `UPDATE` each, applied to the latest version of the row.

Deadlocks are possible exactly as before: the row locks taken are the same,
T1's are only taken one statement earlier. Two opposite T7 transfers between
the same two products can still deadlock, and pgbench retries those. Citus
gives no single snapshot across nodes at any isolation level, so nothing that
crosses shards changes either.

### Recording plans

`explain/T1_place_order.sql` now also plans the stock check on its own, with
`FOR UPDATE OF i`, because inside `place_order` it runs on the worker and does
not appear in the plan of the call. It is planned without `ANALYZE`, so no row
is locked.

### What could get worse

- **Waiting on hot rows.** T1s for the same hot merchant now queue on its
  rollup row instead of failing. Each holds that row from its upsert until
  commit, which includes the `order_merchant_map` insert on another worker
  (and the new connection that needs, see `expt_b10/optimisations.md`) and the
  two-phase commit. The wait is no longer than before, but it is now always
  paid instead of being turned into a retry.
- **Inventory rows are locked one statement earlier**, from the check rather
  than the decrement. The two statements are adjacent, so this adds very
  little.

### What to look at when this is run

- **`explain.log`.** The stock check's plan shows `Task Count: 1` and a
  `LockRows` node: Citus routes the locking read to one shard. If it reports
  an error instead, do not trust the benchmark results: every T1 would fail.
- **Errors.** `serialization_failures` should be 0 at every client count,
  and `retried_transactions` should fall to the deadlocks alone (7649 retried
  at 64 clients in `expt_b13`). `failed_log_records` should be 0. A non-zero
  count with a `check constraint` error in `benchmark.log` would mean the
  stock check is not protecting the decrement.
- **T1 at 32 and 64 clients**: average 20.3 and 37.4 ms in `expt_b13`, p99
  68.6 and 146.5 ms. The overall p99 at 64 clients was 74.0 ms. These are
  where the retries were.
- **Throughput** against `expt_b13` and `expt_b14`, at every client count.
- **Comparability.** Run on the same nodes as `expt_b13` (`xcnf[17-21]`).

### Note: this experiment has not been run yet

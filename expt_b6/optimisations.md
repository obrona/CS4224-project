### Prev: expt_b5

This experiment keeps `expt_b5`'s `order_merchant_map` lookup for T5 but stops
T1 from maintaining it at runtime. There is no other change to the schema, data
distribution, indexes, or server parameters, and the routed path of T5 is
unchanged from `expt_b5`.

`expt_b5` fixed T5 (Update Order Status). Against `expt_b4`:

| T5                      | expt_b4 | expt_b5 |
| ----------------------- | ------- | ------- |
| Avg latency, 1 client   | 6.26 ms | 1.42 ms |
| Avg latency, 64 clients | 1544 ms | 30.7 ms |
| Retries, 64 clients     | 184     | 0       |

Howeverm T1 became slightly slower at 1 client (18.03 ms to 18.88 ms,
+5%), and at 64 clients the run was less robust:

| 64 clients                                   | expt_b4 | expt_b5 |
| -------------------------------------------- | ------- | ------- |
| T1 retries                                   | 54      | 151     |
| T1 transactions that exhausted `--max-tries` | 1       | 8       |
| T6 retries                                   | 26      | 449     |
| Failed log records (all transactions)        | 1       | 9       |

Overall throughput at 64 clients moved only from 369 to 407 TPS, because the
cluster is now saturated by T6. What `expt_b5` cannot say is how much of T1's
extra retries and failures come from maintaining the map — an extra round trip
plus a transaction that now spans two colocation groups and commits by
two-phase commit — and how much simply come from more concurrent writers. T1's
retries at 32 clients actually fell (68 to 56), so the effect is not monotone.
This experiment isolates it.

### Optimisation 1: Load the map once; T1 no longer maintains it

T1 is reverted to `expt_b4`'s version, byte for byte: the map insert and the
`\gset` that fed it are gone, so T1 is again a single round trip that commits
on one worker. `order_merchant_map` is filled only in `generate_data`, from
`SELECT order_id, merchant_id FROM orders`, and is rebuilt on every database
reset. Orders created during the run are therefore not in the map.

For this workload that is safe, because none of the nine transactions can
create a lookup that misses:

- No transaction deletes anything, and none changes an order's `merchant_id`
  (T1 only inserts orders; T5 only sets `order_status`), so a row in the map
  never goes stale.
- T5 is the only transaction the driver hands an `order_id`. T1 generates its
  own from a sequence, and T3 reaches orders through merchant and customer.
- T5 draws `order_id` from `random(1, :INITIAL_NUM_ORDERS)` (this line is in
  the provided `expt_b0` T5), and `INITIAL_NUM_ORDERS` is `MAX(order_id)` after
  the load. T1's new orders come from a sequence that starts at `MAX + 1`, so
  T5 never asks for an order created during the run.

This is an argument about the workload, not a guarantee enforced by the
database: nothing in the schema stops a transaction with a wider `order_id`
range from missing the map. Optimisation 2 removes that dependency.

### Optimisation 2: T5 falls back when the map has no row

T5's lookup now always returns exactly one row, which `\gset` requires:

```sql
SELECT COALESCE(MAX(merchant_id), 0) AS merchant_id
FROM order_merchant_map
WHERE order_id = (:order_id)::bigint
\gset t5_
```

`order_id` is the primary key, so `MAX` is exact, and the aggregate over zero
rows yields `NULL`, which becomes `0`. T5 then branches:

- `merchant_id > 0`: the same routed `UPDATE ... WHERE merchant_id = ... AND
order_id = ...` as `expt_b5`, one shard.
- `merchant_id = 0`: an un-routed `UPDATE ... WHERE order_id = ...`, exactly as
  `expt_b4` did. It searches every `orders` shard but is always correct.

Without the fallback a miss would make `\gset` fail on zero rows. With it, a
miss degrades to `expt_b4`'s performance instead of an error, so T5's
correctness no longer depends on its `order_id` range at all. Under this
workload the fallback should never run, and the three routed statements are
identical to `expt_b5`'s.

### What to compare

Check first that the runs are comparable: at 1 client the unchanged
transactions (T2, T3, T4, T6, T7, T8, T9) should be within about 2% of
`expt_b5`'s, as `expt_b5` was of `expt_b4`'s. Then:

- **T1** should return to `expt_b4`'s cost (about 18.0 ms at 1 client). If its
  64-client retries and exhausted-retry failures also fall back towards
  `expt_b4`'s 54 and 1, the map insert was responsible. If they stay near
  `expt_b5`'s 151 and 8, they are a load effect: with T5 no longer parking
  clients, all 64 are busy and contend, independent of the map.
- **T5** should stay near `expt_b5`'s 1.4 ms at 1 client and about 31 ms at 64.
  A value drifting towards `expt_b4`'s 1544 ms would mean the fallback is
  firing, i.e. the assumption in Optimisation 1 does not hold.
- **T6** is expected to remain the dominant cost regardless. It holds about 42
  of the 64 clients in `expt_b5`, and has no `merchant_id` predicate to route
  on.

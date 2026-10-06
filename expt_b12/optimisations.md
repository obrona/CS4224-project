### Prev: expt_b9

This experiment merges T7 (Inventory Transfer)'s two product-to-merchant
lookups into one statement. `product_merchant_map` stays a distributed table
sharded by `product_id`, as in `expt_b9`.

It is one cell of a two-by-two comparison of T7's lookup:

|                             | Two lookup statements | One merged lookup |
| --------------------------- | --------------------- | ----------------- |
| Map sharded by `product_id` | `expt_b9`             | `expt_b12`        |
| Map as a reference table    | `expt_b11`            | `expt_b13`        |

`expt_b12` isolates the effect of merging the lookups, without the reference
table and the coordinator registration that `expt_b11` and `expt_b13` add.

### Motivation

In `expt_b9` (job-883179) T7 is the largest share of latency at every client
count: 36.2% at 1 client, 37.0% at 8 and 45.6% at 64. It takes 4.6 ms at 1
client although each of its statements executes in 0.09 to 0.20 ms on the
shard and takes 1.1 to 1.7 ms end to end. Its routed path sends 6 statements
one after another: two map lookups, `BEGIN`, the debit, the credit and
`COMMIT`.

The two lookups are independent: neither needs the other's result. Only the
transfer that follows needs both.

### Optimisation: one lookup statement instead of two

```sql
SELECT COALESCE(MAX(merchant_id) FILTER (WHERE product_id = :source_product_id), 0) AS source_merchant_id,
       COALESCE(MAX(merchant_id) FILTER (WHERE product_id = :dest_product_id), 0)   AS dest_merchant_id
FROM product_merchant_map
WHERE product_id IN (:source_product_id, :dest_product_id)
```

Citus prunes the `IN` list to the shards that hold the two products: one task
when both are on the same shard, otherwise two, which it runs in parallel.
Either way pgbench sends one statement and waits for one reply instead of two
in sequence. Each shard computes its part of both `MAX ... FILTER`
aggregates and the coordinator combines them.

T7 now sends 5 statements through the coordinator instead of 6. The trade-off
is on the coordinator: a routed single-shard lookup is planned on Citus's
fast path, while this statement is an aggregate over up to two shards, which
takes the general planner and a final combine step.

### Why T7 still behaves like expt_b0

- **Same answers.** Each column is the merchant of one product, or 0 when
  that product is not in the map, as each separate lookup returned before.
  When the two ids are equal both columns hold the same merchant, and the
  existing `source_product_id = dest_product_id` check still rejects the
  transfer.
- **Same timing.** The lookups ran outside the transfer's transaction in
  `expt_b9` too. Both ids are now read in the same statement, and the map
  never changes during the benchmark, so this makes no difference to the
  result.
- The debit, the credit and the fallback path are unchanged.

### Recording plans

`explain/T7_inventory_transfer.sql` runs the merged lookup once before the
EXPLAIN, so the plan is not the session's first read of the map, then shows
it with `ANALYZE`. The debit and credit are shown as before, inside
`BEGIN ... ROLLBACK`.

### Results (job-886108)

`explain.log` shows the merged lookup as one statement with `Task Count: 2`
(the two test products are on different shards), taking 0.96 ms in total.

| Clients | `expt_b9` TPS | `expt_b12` TPS | Change | T7 avg, `expt_b9` | T7 avg, `expt_b12` |
| ------- | ------------- | -------------- | ------ | ----------------- | ------------------ |
| 1       | 263.1         | 270.9          | +3.0%  | 4.59 ms           | 4.06 ms            |
| 4       | 1187.7        | 1245.9         | +4.9%  | 3.53 ms           | 3.07 ms            |
| 8       | 2642.1        | 2699.8         | +2.2%  | 3.73 ms           | 3.33 ms            |
| 16      | 3386.2        | 3430.6         | +1.3%  | 6.59 ms           | 6.03 ms            |
| 32      | 3792.3        | 3838.0         | +1.2%  | 12.45 ms          | 11.34 ms           |
| 64      | 3897.1        | 3920.0         | +0.6%  | 24.93 ms          | 22.18 ms           |

- **T7 is 9 to 13% faster** at every client count, consistent with one
  lookup wait fewer.
- **The gain in throughput shrinks as clients increase**, from 3 to 5% at 1
  to 4 clients to 0.6% at 64. At high client counts the extra planning work
  of the multi-shard aggregate on the coordinator offsets part of the saved
  wait.
- **The comparison with `expt_b9` is clean.** T2, T4, T8 and T9 never touch
  the map, and their latencies are within 5% of `expt_b9`'s at every client
  count (mostly within 3%), so the two runs saw the same conditions.
- **Retries rose** at 64 clients, from 5996 to 6895 retried transactions,
  and serialization failures from 83 to 121. Almost all of them are T1's (see
  `expt_b13/optimisations.md` and `expt_b14/optimisations.md`). They grow
  with throughput.

`expt_b13` adds the reference table on top of this merged lookup and is
faster again at every client count.

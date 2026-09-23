### Prev: expt_b4

This experiment routes T5 (Update Order Status) to the shard that holds its
order, using a new lookup table `order_merchant_map`. There is no other change
to the schema, data distribution, indexes, the other transactions, or server
parameters carried over from `expt_b4`.

### Motivation

`expt_b4` removed T7 as the bottleneck: T7's average latency fell from 860.6 ms
to 9.0 ms at 64 clients, and overall throughput rose from 239.8 to 367.1 TPS.
That made a transaction which had never mattered before into the one that now
sets throughput.

Each transaction's share of total measured latency in `expt_b4`
(`avg_latency_ms` x `successful_transactions`, over the workload total):

| Transaction            | Share at 1 client | Share at 64 clients |
| ---------------------- | ----------------- | ------------------- |
| T5 Update Order Status | 7.5%              | 88.8%               |
| T6 Global Sales        | 50.0%             | 7.2%                |
| T1 Place Order         | 22.1%             | 1.9%                |
| T7 Inventory Transfer  | 15.8%             | 1.5%                |

T5's latency across client counts in `expt_b4` is 6.3, 10.6, 44.0, 211.5,
685.4, 1554.3 ms, while its throughput stays flat at about 36 TPS from 4
clients onwards. A transaction whose throughput stops rising while its latency
grows in proportion to the client count is saturated. By Little's law
36.59 x 1.554 = 56.9, so about 57 of the 64 clients are inside T5 at any
moment. T5 is 10% of workload B, so 36.59 / 0.10 = 366 TPS, which is the
observed overall throughput (367.1).

The same T5 statement measured 9.3 ms at 64 clients in `expt_b3`. It is 167
times slower in `expt_b4` without having been modified. In `expt_b3` T7 held
62 of the 64 clients, so few T5s ever ran at the same time; once T7 became
cheap, T5 ran at full concurrency and its cost became visible.

### Why T5 is slow

T5 receives only an `order_id`. Since `expt_b1`, `orders` is distributed by
`merchant_id`, and T5's `UPDATE` does not name it:

```sql
UPDATE orders
SET order_status = 'PENDING'::text
WHERE order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'PENDING'::text;
```

Citus cannot prune it, so it is sent to all 32 `orders` shards on all 4
workers. `PRIMARY KEY (merchant_id, order_id)` does not lead with `order_id`,
so no shard can answer with a single index probe either. Every T5 therefore
takes write locks on every shard, which is why concurrent T5s serialise against
each other rather than spreading across the cluster.

The `IS DISTINCT FROM` guard from `expt_b2` does not help here. It prevents the
heap write when the status already matches, but the statement is still sent to
all 32 shards to discover that.

### Optimisation 1: order_merchant_map

Added a two-column table that maps each order to the merchant that owns it:

```sql
CREATE TABLE order_merchant_map (
  order_id BIGINT NOT NULL,
  merchant_id BIGINT NOT NULL,
  PRIMARY KEY (order_id)
);
SELECT create_distributed_table('order_merchant_map', 'order_id', colocate_with => 'none');
```

It is distributed by `order_id`, so a lookup by `order_id` is routed to one
shard. It is filled in `generate_data` straight after `orders` is loaded:

```sql
INSERT INTO order_merchant_map (order_id, merchant_id)
SELECT order_id, merchant_id FROM orders;
```

It is added to the `TRUNCATE` in `generate_data`, so every database reset
rebuilds it along with the tables it is derived from, and the whole-database
`ANALYZE` at the end of `generate_data` covers it.

This is the same pattern as `product_merchant_map`, added for T7 in `expt_b4`.

#### Keeping the map correct

No transaction changes an existing order's merchant, and T5 draws its
`order_id` from `1..INITIAL_NUM_ORDERS`, which is exactly the set of orders
present when the map is built. T1 creates orders beyond that range at run time
and does not add them to the map, but T5 can never select one, so the map
covers every order T5 can reach for the whole run.

As in `expt_b4`, T5 does not depend on that being true: a miss returns
`merchant_id = 0` and T5 falls back to `expt_b4`'s un-routed statement. Under
this workload the fallback should never run.

### Optimisation 2: Routed T5

T5 now runs a lookup, routed to one `order_merchant_map` shard:

```sql
SELECT COALESCE(MAX(merchant_id), 0) AS merchant_id
FROM order_merchant_map
WHERE order_id = (:order_id)::bigint
\gset t5_
```

`COALESCE(MAX(...), 0)` always returns exactly one row, as `\gset` requires,
and turns a miss into `0`. Then the same `UPDATE` as before, with `merchant_id`
added:

```sql
UPDATE orders
SET order_status = 'PENDING'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'PENDING'::text;
```

This is routed to one shard and uses the complete
`PRIMARY KEY (merchant_id, order_id)`. The three status branches and the
`IS DISTINCT FROM` guard are unchanged, so the only difference from `expt_b4`
is which shards the statement reaches.

T5 has no `BEGIN`/`COMMIT` — it has been a single-statement transaction since
`expt_b1`'s Optimisation 1, and remains one plus a preceding read. The lookup
is therefore its own autocommit statement. Nothing writes the map, so reading
it separately cannot give a different answer than reading it inside a
transaction would.

Per execution, this goes from 1 statement x 32 shards to 1 single-shard lookup
plus 1 single-shard `UPDATE`.

### Expected effect

T5 should join T2, T8 and T9 at roughly 1-2 ms instead of 1554 ms, and stop
capping throughput at 366 TPS. T6 (Global Sales) is the next candidate: it is
un-routable by construction, since it aggregates across all merchants, and it
is already 50% of latency at 1 client and 7.2% at 64.

### What to look at when this is run

- **Comparability.** Run on the same nodes as `expt_b4` (`xcnf[16-20]`). At 1
  client the unchanged transactions (T1, T2, T3, T4, T6, T7, T8, T9) should be
  within a few percent of `expt_b4`.
- **T5 latency and its curve across client counts.** The flat ~36 TPS ceiling
  should disappear. A T5 p99 anywhere near `expt_b4`'s p50 would mean the
  fallback is firing.
- **The next bottleneck.** Recompute the latency-share table. If T6 takes over,
  overall throughput should settle near (T6 TPS) / 0.10.
- **T1 latency.** T1 writes `orders` too, on the merchant's shard. Removing 32
  shard-wide write locks per T5 should help T1 as well; if it does not, the
  contention was somewhere else.
- **`pgbench_exit_code` and `failed_log_records`.**

### Note: this experiment has not been run yet

This folder contains no `slurm-results/`.

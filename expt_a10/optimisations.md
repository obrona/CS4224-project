### Prev: expt_a9

This experiment routes T5 (Update Order Status) to the shard that holds its
order, using a new lookup table `order_merchant_map` that T1 maintains. It is
a port of `expt_b5` onto the A-side design; `expt_b4`'s T7 routing is not
included. Apart from that addition to T1, there is no change to the schema,
data distribution, indexes, the other transactions, or server parameters
carried over from `expt_a9`.

`expt_a10`, `expt_a11` and `expt_a12` form a 2x2 on top of `expt_a9`:

| Experiment | T5 routing (this) | T6 rollup (`expt_a11`) |
| ---------- | ----------------- | --------------------- |
| `expt_a9`  |                   |                       |
| `expt_a10`  | yes               |                       |
| `expt_a11`  |                   | yes                   |
| `expt_a12`  | yes               | yes                   |

Both optimisations add a write to T1, which is 36% of workload A, so their
costs on T1 are not assumed to be additive. `expt_a12` measures the pair.

### Motivation

Each transaction's share of total measured latency in `expt_a9`
(`avg_latency_ms` x `successful_transactions`, over the workload total):

| Transaction            | Share at 1 client | Share at 8 clients | Share at 64 clients |
| ---------------------- | ----------------- | ------------------ | ------------------- |
| T1 Place Order         | 54%               | 47%                | 9%                  |
| T6 Global Sales        | 23%               | 20%                | 4%                  |
| T7 Inventory Transfer  | 14%               | 17%                | 6%                  |
| T5 Update Order Status | 6%                | 13%                | 81%                 |

T5's average latency grows from 6.8 ms at 1 client to 31.3 ms at 8 and
1540.3 ms at 64, while throughput stays flat at about 330 TPS from 8 clients
up. At 64 clients T5 alone accounts for four fifths of all time spent in
transactions.

### Why T5 is slow

T5 is given only an `order_id`, but `orders` is distributed by `merchant_id`.
Its `UPDATE ... WHERE order_id = ...` therefore cannot be routed: Citus sends
it to every `orders` shard, which opens a transaction on every worker and,
under `SERIALIZABLE`, reads across every shard of `orders`. Every T5 therefore
overlaps with every concurrent writer of `orders` on every worker, which is
the likely reason its latency grows with the client count far faster than any
single-shard transaction's.

### Optimisation 1: order_merchant_map

Added a two-column table mapping each order to its merchant:

```sql
CREATE TABLE order_merchant_map (
  order_id BIGINT NOT NULL,
  merchant_id BIGINT NOT NULL,
  PRIMARY KEY (order_id)
);
SELECT create_distributed_table('order_merchant_map', 'order_id', colocate_with => 'none');
```

It is distributed by `order_id`, so a lookup by `order_id` goes to one shard.
It is filled in `generate_data` straight after `orders` is loaded, and it is
part of the `TRUNCATE` there so every reset rebuilds it.

#### Keeping the map correct

T1 creates orders, so a load-time map goes stale as soon as the benchmark
starts. T1 therefore inserts the new order's map row inside the same
`BEGIN`/`COMMIT` that inserts the order:

```sql
INSERT INTO order_merchant_map (order_id, merchant_id)
VALUES ((:t1_new_order_id)::bigint, (:merchant_id)::bigint);
```

An order and its map row become visible together, so a lookup can only miss
when the order does not exist. This is deliberately not left to the fact that
T5 only draws `order_id` from the initial range while `benchmark_order_id_seq`
starts above it; that is a property of the benchmark parameters, not of the
design.

#### What the maintenance costs

`order_merchant_map` is in its own colocation group, so the new map row
usually lands on a different worker from the merchant's shards. T1 was a
single-worker transaction in `expt_a9`; it now spans two workers and commits
in two phases. That cost is paid on every T1, 36% of workload A (against 10%
in workload B), so T1's latency at 1 client against `expt_a9` is the price to
read off this experiment.

### Optimisation 2: Routed T5

T5 first looks up the merchant, routed to one `order_merchant_map` shard:

```sql
SELECT COALESCE(MAX(merchant_id), 0) AS merchant_id
FROM order_merchant_map
WHERE order_id = (:order_id)::bigint
\gset t5_
```

and then names it in the update, which sends the update to one shard and
gives PostgreSQL the full primary key `(merchant_id, order_id)`:

```sql
UPDATE orders
SET order_status = 'PENDING'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'PENDING'::text;
```

On a miss (`merchant_id = 0`) T5 falls back to `expt_a9`'s un-routed update.
With T1 maintaining the map that path should be unreachable; it is kept so
that a stale map gives a slow answer instead of silently updating nothing
through `WHERE merchant_id = 0`.

### What to look at when this is run

- **T5 latency at 64 clients**, 1540.3 ms in `expt_a9`. In `expt_b5` the same
  change took it from 1554.3 ms to 28.5 ms.
- **T1 latency at 1 client**, 17.2 ms in `expt_a9`. The increase is the cost
  of the map write and the two-phase commit.
- **`pgbench_exit_code` and `failed_log_records`.** T1 now commits on two
  workers. `expt_a8` lost clients to non-retriable
  `could not commit transaction for shard ...` errors, and `expt_b6` exited
  with code 2 at 64 clients; any client that aborts invalidates that client
  count.
- **The next bottleneck.** Recompute the latency-share table; T6 and T1 are
  the expected candidates.
- **Comparability.** Pinned to `xcnf[1,3-6]`, the same nodes as `expt_a0` to
  `expt_a9`. Check that T2, T3, T4, T8 and T9 land within about 2% of
  `expt_a9` at 1 client before attributing any delta.

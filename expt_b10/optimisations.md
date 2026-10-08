### Prev: expt_b9

This experiment routes T7 (Inventory Transfer) to the shards that hold its two
inventory rows, using a new lookup table `product_merchant_map`. There is no
other change to the schema, data distribution, indexes, the other transactions,
or server parameters carried over from `expt_b9`.

Each transaction's share of total measured latency in `expt_b9`
(`avg_latency_ms` x `successful_transactions`, over the workload total):

| Transaction            | Share at 1 client | Share at 64 clients |
| ---------------------- | ----------------- | ------------------- |
| T7 Inventory Transfer  | 57.1%             | 96.8%               |
| T6 Global Sales        | 25.3%             | 2.1%                |
| T1 Place Order         | 11.2%             | 0.6%                |
| T5 Update Order Status | 3.9%              | 0.4%                |

At 64 clients T7 runs at 70.0 TPS with an average latency of 885 ms, so by
Little's law about 62 of the 64 clients are inside T7 at any moment. T7 is 30%
of workload B, and 70.0 / 0.30 = 233 TPS, which is the observed overall
throughput (233.2). The same calculation gives `expt_b8`'s 237.1 TPS from its
T7 rate (71.2 / 0.30 = 237.2). Overall throughput is set entirely by how fast
T7 can run, so T7 is the only transaction worth changing next.

### Why T7 is slow

T7 receives only `source_product_id`, `dest_product_id` and `transfer_qty`.
Since `expt_b7`, `inventory` is distributed by `merchant_id`, and none of T7's
six statements names it:

- two `EXISTS` probes and two `SELECT inventory_id` lookups by `product_id`
- a debit and a credit `UPDATE` by `inventory_id`

Citus cannot prune any of them, so each is sent to all 32 `inventory` shards
across all 4 workers: about 192 shard queries per transfer. None of the
`inventory` indexes leads with `product_id` or `inventory_id` alone
(`PRIMARY KEY (merchant_id, inventory_id)`, `UNIQUE (merchant_id, product_id)`),
so no shard can answer with a single index probe either. And because both
`UPDATE`s touch every shard, every worker takes part in every T7 write and in
its two-phase commit, whichever two rows actually change.

### Optimisation 1: product_merchant_map

Added a two-column table that maps each product to the merchant that owns it:

```sql
CREATE TABLE product_merchant_map (
  product_id BIGINT NOT NULL,
  merchant_id BIGINT NOT NULL,
  PRIMARY KEY (product_id)
);
SELECT create_distributed_table('product_merchant_map', 'product_id', colocate_with => 'none');
```

It is distributed by `product_id`, so a lookup by `product_id` is routed to one
shard. It is filled in `generate_data` straight after `products` is loaded:

```sql
INSERT INTO product_merchant_map (product_id, merchant_id)
SELECT product_id, merchant_id FROM products;
```

It is added to the `TRUNCATE` in `generate_data`, so every database reset
rebuilds it along with the tables it is derived from, and the whole-database
`ANALYZE` at the end of `generate_data` covers it.

This is the same pattern as the `order_merchant_map` used for T5 on the
earlier, discarded branch.

#### Keeping the map correct

No transaction in the workload inserts a product or changes a product's
merchant (T9 changes only `price`), so a map built at load time stays exact for
the whole run. That is a property of this workload, not something the schema
enforces, so T7 does not depend on it: a miss returns `merchant_id = 0` and T7
falls back to `expt_b9`'s un-routed statements. Under this workload the
fallback should never run.

### Optimisation 2: Routed T7

T7 now runs:

1. Two lookups, one per product, each routed to one `product_merchant_map`
   shard:

   ```sql
   SELECT COALESCE(MAX(merchant_id), 0) AS source_merchant_id
   FROM product_merchant_map
   WHERE product_id = (:source_product_id)::bigint
   \gset t7_
   ```

   `COALESCE(MAX(...), 0)` always returns exactly one row, as `\gset` requires,
   and turns a miss into `0`. This is the same form as the discarded branch's
   T5 lookup.

2. `BEGIN`, then the same debit and credit as before, with `merchant_id` added
   to each `WHERE` and the row identified by `product_id` instead of a
   previously fetched `inventory_id`:

   ```sql
   UPDATE inventory
   SET quantity = quantity - (:transfer_qty)::integer,
       updated_at = CURRENT_TIMESTAMP
   WHERE merchant_id = (:t7_source_merchant_id)::bigint
     AND product_id = (:source_product_id)::bigint
     AND quantity >= (:transfer_qty)::integer
   ```

   Each `UPDATE` is routed to one shard and uses the
   `UNIQUE (merchant_id, product_id)` index.

3. `COMMIT` if both `UPDATE`s changed a row, otherwise `ROLLBACK`, exactly as
   before.

The four probes are removed. They existed only to find `inventory_id` and to
roll back when a product has no inventory row. The routed `UPDATE`s find the
row themselves, and a missing row makes its `UPDATE` affect zero rows, which
already triggers the rollback.

The lookups run before `BEGIN`. No transaction writes the map, so reading it
outside the transfer cannot see a different answer than reading it inside. It
also keeps the lookup's workers out of T7's distributed transaction, so only
the one or two workers holding the changed rows take part in the commit. If the
map were ever wrong, the routed `UPDATE` would match no row and the transfer
would roll back. A stale map can make a transfer fail, but it cannot make one
change the wrong row.

Per transfer, this goes from 6 statements x 32 shards with all 4 workers in the
commit, to 2 single-shard lookups plus 2 single-shard `UPDATE`s with 1 or 2
workers in the commit.

### What this cannot remove

The source and destination products are independent random draws, so under
any single-column hash distribution their rows are on different workers most
of the time (3 in 4 with 4 workers). Those transfers still commit with
two-phase commit across two workers. Routing removes the fan-out, not the
cross-node commit. `expt_b11` tests a layout that removes the cross-node commit
as well.

### What to look at when this is run

- **Comparability.** Run on the same nodes as `expt_b9` (`xcnf[17-21]`). At 1
  client the unchanged transactions (T2, T3, T4, T5, T6, T8, T9) should be
  within a few percent of `expt_b9`.
- **T7 latency.** `expt_b9` had 32.7 ms at 1 client. The discarded
  formula-routed T7 measured 5.1 ms at 1 client on `xcnf[17-21]`, with the same
  shape of two routed `UPDATE`s. This version adds two routed lookups, so it
  should land slightly above that. A T7 p99 anywhere near `expt_b9`'s p50 would
  mean the fallback is firing.
- **Overall throughput and the next bottleneck.** The discarded formula-routed
  T7 reached 369 TPS at 64 clients. Once T7 stops limiting throughput, expect
  T6 (Global Sales, un-routable and 10% of the workload) to take over, at about
  (T6 TPS) / 0.10.
- **`deadlock_failures`.** Like `expt_b9`, T7 debits before it credits, so two
  opposite transfers between the same pair of products can deadlock across
  workers. With 500,000 products this should stay near zero, but T7 now runs
  several times more often.

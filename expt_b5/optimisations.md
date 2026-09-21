### Prev: expt_b4

This experiment gives T5 (Update Order Status) a routable `merchant_id` by
adding a lookup table sharded by `order_id`. There is no other change to the
schema, data distribution, indexes, the other transaction rewrites, or server
parameters carried over from `expt_b4`, apart from T1 maintaining the new
lookup table.

Computing each transaction's share of total measured latency for `expt_b4`
gives:

| Transaction | Share at 1 client | Share at 64 clients |
| --- | --- | --- |
| T6 Global Sales | 49.2% | 7.2% |
| T1 Place Order | 21.1% | 1.9% |
| T7 Inventory Transfer | 17.9% | 1.7% |
| T5 Update Order Status | 7.3% | 88.7% |

T5's share explodes from 7.3% to 88.7% as concurrency rises, and at 64
clients it accounts for 184 of `expt_b4`'s 269 recorded retries (68%) — the
largest of any transaction, despite T5 being a single `UPDATE`. The reason is
the same one that made T7 dominant before `expt_b3`: `orders` is distributed
and colocated by `merchant_id`, but T5's `UPDATE` filters only on `order_id`,
so Citus cannot route it to one shard and instead searches every `orders`
shard on every worker. Under concurrency that broadcast update contends with
every other in-flight statement across the whole cluster instead of just the
one shard that owns the row.

### Optimisation 1: A lookup table sharded by `order_id`

Added a second distributed table whose distribution column is `order_id`:

```sql
CREATE TABLE IF NOT EXISTS order_merchant_map (
	order_id BIGINT NOT NULL,
	merchant_id BIGINT NOT NULL,
	PRIMARY KEY (order_id)
);

PERFORM create_distributed_table('order_merchant_map', 'order_id', colocate_with => 'none');
```

`orders` is unchanged and still distributed by `merchant_id`; a Citus table can
only have one distribution column, but each table chooses its own, so a second
table may be sharded by a different key. This is the standard way to make rows
findable by a key that is not the distribution column: keep a narrow table
sharded *by that key*. `colocate_with => 'none'` puts it in its own colocation
group, because `order_id` and `merchant_id` values are unrelated and colocating
them would only assert a relationship that does not exist.

It is populated in `generate_data` by reading the loaded rows:

```sql
INSERT INTO order_merchant_map (order_id, merchant_id)
SELECT order_id, merchant_id FROM orders;
```

This is a repartitioning `INSERT ... SELECT` (source and destination are not
colocated), and it runs once per data load — including each
`reset_benchmark_database` between client counts. The table is also added to
the `DROP TABLE` and `TRUNCATE` lists so a reset cannot leave it stale.

A Citus *reference table* would also have worked for the lookup itself, and was
considered. It was rejected because a reference table is replicated to every
worker: populating it would write the whole map to all four workers on every
reset, and any maintenance write would have to update all four replicas inside
a distributed transaction holding locks that serialize concurrent writers.
Since T1 writes to this table on every execution (Optimisation 3), that cost
would fall directly on the workload's second-heaviest transaction.

### Optimisation 2: Route T5 through the lookup

T5 now resolves the merchant before updating:

```sql
SELECT merchant_id
FROM order_merchant_map
WHERE order_id = (:order_id)::bigint
\gset t5_
```

and adds `merchant_id = (:t5_merchant_id)::bigint` to all three branches
(`PENDING` / `SHIPPED` / `COMPLETED`) of the status `UPDATE`. Both statements
are now single-shard router queries: the lookup prunes to one
`order_merchant_map` shard because `order_id` is that table's distribution
column, and the `UPDATE` prunes to one `orders` shard because `merchant_id` is
supplied. This replaces one cluster-wide broadcast with two single-worker
round trips.

No `BEGIN`/`COMMIT` was added. The two statements run as separate implicit
transactions, which is safe because an order's `merchant_id` is immutable once
the order exists — no transaction in the workload ever updates it — so the
value read by the lookup cannot be stale by the time the `UPDATE` runs.

### Optimisation 3: T1 maintains the lookup

So that the map covers orders created during the benchmark and not just the
initial load, T1's final statement now also returns the `order_id` it
generated, and a following statement records the mapping:

```sql
SELECT
  EXISTS (SELECT 1 FROM inserted_order) AS order_created,
  (SELECT COUNT(*) FROM inserted_items) AS items_created,
  COALESCE((SELECT order_id FROM inserted_order), 0) AS new_order_id
\gset t1_

\if :t1_new_order_id > 0
INSERT INTO order_merchant_map (order_id, merchant_id)
VALUES ((:t1_new_order_id)::bigint, (:merchant_id)::bigint);
\endif
```

The `COALESCE(..., 0)` is required because `\gset` cannot bind a NULL, and the
order is not always created (the eligibility check in `expt_b4`'s rewrite can
reject it); `0` then means "no order, nothing to record".

This insert cannot be folded into the large CTE statement above it, because
Citus will not modify two non-colocated distributed tables in one statement,
and `order_merchant_map` is deliberately not colocated with `orders`. The cost
is therefore real and worth stating plainly:

- T1 goes from one round trip back to two, partially undoing what `expt_b4`
  set out to achieve.
- T1's transaction now touches two colocation groups, so it commits by
  two-phase commit across two workers instead of committing on one.

The alternative was to populate the map only at load time and let T5 fall back
to the un-routed `UPDATE` on a lookup miss. That is cheaper — T1 would be
untouched — and T5 provably never asks for a missing order, because it draws
`order_id` from `random(1, :INITIAL_NUM_ORDERS)` while T1's new orders come
from a sequence starting above `INITIAL_NUM_ORDERS`. It was not chosen because
the optimisation's benefit would then quietly depend on that property of the
benchmark driver rather than holding unconditionally. If T1's added cost turns
out to outweigh T5's gain, that cheaper variant is the first thing to try.

### Expected effect

T5 should drop from dominating latency at high client counts to roughly the
cost of two routed statements, and its retries should fall towards zero, since
a single-shard update cannot conflict with concurrent work on other shards.
T1 should get measurably slower for the reasons above. The net direction is not
obvious from the change alone: T5 and T1 carry the same 10% workload weight,
but T5 accounted for 88.7% of latency at 64 clients in `expt_b4` against T1's
1.9%, so the trade should be strongly favourable.

`expt_b4`'s figures also predict what becomes dominant next. Removing T5's
88.7% leaves T6 Global Sales as the largest remaining cost — it was already
49.2% at 1 client — and T6 has no `merchant_id` predicate at all, since it
reports revenue over a date range across every merchant. Like T7's
cross-merchant transfers before `expt_b3`, that is inherent to what the
transaction computes rather than a missing predicate, so the routing technique
used here does not apply to it.

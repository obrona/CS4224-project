### Prev: expt_b7

This experiment applies the same three transaction rewrites as `expt_a2`, with
no change to the database schema, data distribution, indexes, or server
parameters.

The motivation comes from the per-transaction cost breakdown of `expt_b7`.
Computing each transaction's share of total measured latency
(`avg_latency_ms` x `successful_transactions`, over the workload total) gives:

| Transaction | Share at 1 client | Share at 64 clients |
| --- | --- | --- |
| T3 Customer Order History | 85.6% | 40.7% |
| T7 Inventory Transfer | 8.0% | 14.8% |
| T1 Place Order | 1.6% | 21.6% |
| T5 Update Order Status | 0.6% | 20.7% |

T3 dominates at every client count despite being only 5% of workload B, so it
is addressed first.

### Optimisation 1

Added `merchant_id` to the join predicate in T3:

```sql
ON oi.order_id = o.order_id
AND oi.merchant_id = o.merchant_id
```

Both `orders` and `order_items` are distributed by `merchant_id` and colocated
in expt_b7. Equating their distribution columns makes the colocation explicit
to Citus, so the merchant-scoped query can be routed to one worker without a
repartition join. It also lets PostgreSQL use
`idx_order_items_order (merchant_id, order_id)` for the item lookup.

The baseline T4 already joins `products` and `inventory` on both
`product_id` and `merchant_id`; T3 was the one join in the workload written
without its distribution column, so this change makes T3 consistent with the
rest of the provided transactions.

### Optimisation 2

Added `IS DISTINCT FROM` predicates to T5 and T8 so PostgreSQL updates a row
only when the new value differs from its current value. For example, T5 now
uses:

```sql
UPDATE orders
SET order_status = 'PENDING'::text
WHERE order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'PENDING'::text;
```

PostgreSQL normally creates a new row version even when an `UPDATE` assigns the
existing value. Skipping such updates avoids unnecessary heap tuple creation,
WAL generation, row locking, and later vacuum work. The transaction still
completes successfully when the requested value is already present; the SQL
statement simply affects zero rows.

The expected benefit is mainly in T5 because its requested status is chosen
from only three values, and the generated orders all start at `COMPLETED`.
T8 has the same guard, but its randomly generated email is unlikely to match
the existing email. T9 is unchanged because its positive price increase always
produces a different value.

This is a small rewrite that does not change distribution, indexes,
transaction inputs, or query results. T5 still lacks `merchant_id` in its
predicate and therefore still has a separate cross-shard routing cost, which
this optimisation does not address.

### Optimisation 3

Added `merchant_id` to T1's final `UPDATE orders` predicate:

```sql
UPDATE orders
SET total_amount = (:order_total)::numeric(12,2)
WHERE merchant_id = (:merchant_id)::bigint
  AND order_id = (:new_order_id)::bigint;
```

The `orders` table is distributed by `merchant_id` and has the composite
primary key `(merchant_id, order_id)`. Supplying both columns lets Citus route
the update directly to the merchant's shard and gives PostgreSQL the complete
primary-key lookup. It does not change the transaction's result because the
new order was inserted using the same `merchant_id` earlier in T1.

### Prediction for this experiment

The expectation is that T7 becomes the dominant remaining cost in workload B
after this experiment, in a way it never was in workload A. `expt_b9` will test
that by adding `merchant_id` routing to T7.

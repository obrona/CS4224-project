### Prev: expt a7

### Optimisation 1

Added `merchant_id` to the join predicate in T3:

```sql
ON oi.order_id = o.order_id
AND oi.merchant_id = o.merchant_id
```

Both `orders` and `order_items` are distributed by `merchant_id` and colocated
in expt_a7. Equating their distribution columns makes the colocation explicit
to Citus, so the merchant-scoped query can be routed to one worker without a
repartition join. It also lets PostgreSQL use
`idx_order_items_order (merchant_id, order_id)` for the item lookup.

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
from only three values. T8 has the same guard, but its randomly generated email
is unlikely to match the existing email. T9 is unchanged because its positive
price increase always produces a different value.

This is a small rewrite that does not change distribution, indexes,
transaction inputs, or query results. T5 still lacks `merchant_id` in its
predicate and therefore still has a separate cross-shard routing cost.

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

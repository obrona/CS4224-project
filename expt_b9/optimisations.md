### Prev: expt_b8

This experiment rewrites T1 (Place Order) as a single set-based statement.
There is no other change to the schema, data distribution, indexes, the other
transactions, or server parameters carried over from `expt_b8`, apart from the
`-D DEBUG_*` defaults that `run.sh` now passes to pgbench (Optimisation 2).

Computing each transaction's share of total measured latency
(`avg_latency_ms` x `successful_transactions`, over the workload total) for
`expt_b8` gives:

| Transaction            | Share at 1 client | Share at 64 clients |
| ---------------------- | ----------------- | ------------------- |
| T7 Inventory Transfer  | 59.9%             | 97.0%               |
| T6 Global Sales        | 27.0%             | 2.1%                |
| T1 Place Order         | 6.4%              | 0.3%                |
| T5 Update Order Status | 4.1%              | 0.4%                |
| T2 Update Inventory    | 0.6%              | 0.0%                |

T1 is not the dominant cost at either client count. T7 is, and this experiment
does not touch it. T1 is targeted for a different reason: it sends by far the
most statements per execution. The original script sends up to 26 statements
inside one `BEGIN`/`COMMIT` — a customer check, an order-id `nextval`, the
`orders` insert, then for each of up to five items a product lookup, a guarded
inventory `UPDATE`, an order-item-id `nextval` and an `order_items` `INSERT`,
and finally `UPDATE orders SET total_amount` (about 18 on average at 1–5
items). Each is a separate coordinator round trip, and the nested pgbench `\if`
blocks needed to skip absent items make the script 438 lines long for what is
logically one order.

### Optimisation 1: Set-based T1

Rewrote the transaction body as one statement built from chained CTEs:

```sql
WITH
input_items(item_no, product_id, quantity) AS ( VALUES (1, ...), (2, ...), ... (5, ...) ),
requested_items AS MATERIALIZED (
  SELECT item_no, product_id, quantity FROM input_items WHERE item_no <= (:item_count)::integer
),
requirements AS MATERIALIZED (
  SELECT product_id, SUM(quantity)::integer AS quantity FROM requested_items GROUP BY product_id
),
eligible AS MATERIALIZED ( ... EXISTS customer ... AND NOT EXISTS (missing product / missing inventory / insufficient stock) ... ),
reserved AS ( UPDATE inventory ... FROM requirements r, eligible e WHERE e.ok ... RETURNING i.product_id ),
reservation_ok AS MATERIALIZED ( SELECT e.ok AND (SELECT COUNT(*) FROM reserved) = (SELECT COUNT(*) FROM requirements) AS ok FROM eligible e ),
inserted_order AS ( INSERT INTO orders(...) SELECT ..., SUM(ri.quantity * p.price), ... FROM requested_items ri JOIN products p ... CROSS JOIN reservation_ok ro WHERE ro.ok HAVING COUNT(*) = (:item_count)::integer RETURNING order_id ),
inserted_items AS ( INSERT INTO order_items(...) SELECT ... FROM requested_items ri JOIN products p ... CROSS JOIN inserted_order o RETURNING 1 )
SELECT EXISTS (SELECT 1 FROM inserted_order), (SELECT COUNT(*) FROM inserted_items);
```

All five item slots are still generated up front by pgbench; the
`requested_items` CTE trims the `VALUES` list to `item_count` rows inside SQL
instead of pgbench skipping whole blocks with `\if :item_count >= N`. Because
every requested product is now reserved by one `UPDATE ... FROM requirements`
rather than one `UPDATE` per item slot in sequence, a product picked in two
slots must have its combined quantity reserved in a single pass. The original
sequential design reached the same net reservation across two statements,
since each saw the previous one's write inside the same transaction. The
`requirements` CTE therefore groups by `product_id` and sums the quantities.

Customer existence, product existence and sufficient stock for every requested
product are checked together in the `eligible` CTE, and the order and its items
are inserted only when that check and the reservation both succeed. The
order's `total_amount` is computed inline with `SUM(quantity * price)`, which
removes the closing `UPDATE orders SET total_amount` that every earlier
experiment needed.

### Optimisation 2: CASE-based DEBUG_MODE handling

Replaced every `\if :DEBUG_MODE ... \else ... \endif` block that chose between
fixed debug values and random generation with a single `\set` using a SQL
`CASE WHEN :DEBUG_MODE = 1 THEN ... ELSE ... END` expression. `run.sh` now
passes harmless defaults for the `DEBUG_*` variables (`-D DEBUG_MERCHANT_ID=1`,
`-D DEBUG_QTY_5=1`, and so on) so those expressions can replace the meta-command
blocks. `DEBUG_MODE` is 0 in every benchmark run, so behaviour is unchanged. It
is what shrinks the script from 438 to 128 lines and lets the CTE statement
read as one block instead of being split across nested `\if` branches.

### Caveat: the stock check now depends on the isolation level

In the original T1 each per-item `UPDATE` carried its own guard,
`AND quantity >= qty`. In the rewrite the sufficiency check lives in the
separate `eligible` CTE, which reads the statement's snapshot, and the
`reserved` `UPDATE` has no such guard. Under `SERIALIZABLE` (the setting used
here) a concurrent decrement of the same inventory row is detected, one of the
two transactions fails with a retriable serialization error, and stock cannot
be over-reserved. Under `READ COMMITTED` two concurrent orders could both pass
the check and both decrement, and the `CHECK (quantity >= 0)` constraint would
then reject the second with an error pgbench does not retry. This form should
not be run at a weaker isolation level without restoring the guard in the
`UPDATE` and rolling back when no order is created, since T1 always commits.

### What to look at when this is run

The trade is fewer round trips against one heavier plan (several materialized
CTEs, joins against `products`, an anti-join-style `NOT EXISTS` and an
aggregating `INSERT ... SELECT`), and which side wins is what this experiment
measures. T1 was only 0.3% of latency at 64 clients in `expt_b8`, so any effect
should show in T1's own latency, most cleanly at 1 client where there is no
contention, rather than in overall throughput, which T7 still dominates.

Also check `pgbench_exit_code` and the number of clients still running at the
end of each measured run. A client that dies on a non-retriable error stops
issuing transactions, so that run's numbers are not for the client count they
are labelled with.

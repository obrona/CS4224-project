### Prev: expt_b3

This experiment rewrites T1 (Place Order) as a single set-based statement.
There is no other change to the schema, data distribution, indexes, the other
transaction rewrites, or server parameters carried over from `expt_b3`.

Computing each transaction's share of total measured latency for `expt_b3`
gives:

| Transaction | Share at 1 client | Share at 64 clients |
| --- | --- | --- |
| T6 Global Sales | 55.3% | 12.2% |
| T7 Inventory Transfer | 19.7% | 3.0% |
| T1 Place Order | 12.2% | 1.5% |
| T5 Update Order Status | 8.0% | 82.4% |

Unlike T5 and T7, T1 was not the single dominant cost at either client count
— but it was already the transaction with the most SQL statements sent per
execution. The original script issued up to 11 sequential statements inside
one `BEGIN`/`COMMIT`: one customer-existence check, then up to five
repetitions of a product-existence check, a conditional `inventory` `UPDATE`,
and a conditional `order_items` `INSERT` (one repetition per item slot,
gated by nested pgbench `\if` blocks), followed by a final
`UPDATE orders SET total_amount`. Each statement is its own
coordinator-to-worker round trip, and the nested `\if` blocks made the script
438 lines long for what is logically one order.

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

All five item slots are generated up front by pgbench (as before); the
`requested_items` CTE trims the `VALUES` list down to `item_count` rows
inside SQL instead of pgbench skipping whole blocks with `\if item_count >=
N`. Because reservation now happens as one `UPDATE ... FROM requirements` for
every requested product at once rather than one `UPDATE` per item slot in
sequence, a product chosen in two of the five slots must have its combined
quantity reserved in a single pass — the original sequential design achieved
the same net reservation across two separate statements, since each ran
inside the same transaction and saw the prior statement's write. The
`requirements` CTE groups by `product_id` and sums the quantities before the
single reservation `UPDATE` runs. Customer existence, product existence, and
sufficient stock for every requested product are all checked in one
`eligible` CTE; the order and its items are only inserted, with
`total_amount` computed inline via `SUM(quantity * price)`, when that check
and the reservation both succeed. This removes the separate closing
`UPDATE orders SET total_amount` statement that every earlier experiment
needed.

### Optimisation 2: CASE-based DEBUG_MODE handling

Replaced every `\if :DEBUG_MODE ... \else ... \endif` block used to choose
between fixed debug values and random generation with a single `\set` using a
SQL `CASE WHEN :DEBUG_MODE = 1 THEN ... ELSE ... END` expression, relying on
`DEBUG_MODE` and the `DEBUG_*` variables having harmless defaults in
`run.sh`. `DEBUG_MODE` is 0 in every benchmark run, so this does not change
behaviour; it is what shrinks the script from 438 to 128 lines and makes the
single CTE statement above legible as one block instead of being split across
nested `\if` branches.

### Observed effect: fewer round trips, but not lower latency

At 1 client — a single connection, so no serialization retries are possible
— T1's own average latency rose from 9.24ms (`expt_b3`) to 18.03ms
(`expt_b4`), while every other transaction's average latency at 1 client
stayed within about 10% of its `expt_b3` value (for example T6: 42.16ms vs.
42.55ms; T7: 4.98ms vs. 5.09ms), so this is not attributable to run-to-run
cluster noise. Consolidating the transaction removed roughly ten network
round trips, but the replacement is a single, heavier plan: multiple
materialized CTEs, two joins against `products`, an anti-join-style
`NOT EXISTS` spanning `products` and `inventory`, and an `INSERT ... SELECT`
with aggregation. On this workload, the added planning/execution cost of that
plan outweighed the round-trip savings.

At 64 clients, T1's retries rose from 5 (`expt_b3`) to 54 (`expt_b4`) even
though system-wide retries fell overall (384 to 269) — consistent with the
new statement's wider read/write footprint (it can touch several rows of
`inventory` and `products` at once) creating more opportunities for a
serializable-isolation conflict than five independent single-row statements
did. T5 is unchanged in this experiment and still accounts for the majority
of both retries (184 of 269, 68%) and latency share (88.7% at 64 clients),
confirming it as the larger remaining bottleneck; `expt_b5` addresses it
directly. The goal of this experiment was closing the round-trip and
statement-count gap in T1's design, not raw latency, and that trade-off is
recorded here rather than treated as a clear win either way.

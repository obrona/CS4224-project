expt_a0 - performance of baseline design as a function of number of clients for workload A

expt_b0 - performance of baseline design as a function of number of clients for workload B

- Result: 6.7 TPS at 1 client, a peak of 7.8 at 16 and 6.4 at 64, with T3 averaging 1.9 s at 1 client and a few clients aborted at 8, 16 and 32 clients on an error pgbench does not retry.

expt_b1 - baseline design for workload B with 2 worker nodes instead of 4

- Result: 4.7 TPS at 1 client and 3.7 at 64, 30% and 42% below `expt_b0`.

expt_b2 - baseline design for workload B with stronger merchant skew: HOT_ORDER_PERCENT 80 instead of 50

- Result: 6.7 TPS at 1 client and 6.0 at 64, at most 6% below `expt_b0` at any client count.

expt_b3 - baseline design for workload B with twice the synthetic data: SCALE 2 instead of 1

- Result: 2.0 TPS at 1 client and 3.4 at 64, 70% and 47% below `expt_b0`, and the 1-client run has unexplained T7 stalls of up to 78 s.

expt_b4 - baseline design for workload B with 8 worker nodes instead of 4

- Result: 9.0 TPS at 1 client and 10.2 at 64, 35% and 59% above `expt_b0`.

expt_b5 - baseline design for workload B with no merchant skew: HOT_ORDER_PERCENT 10 instead of 50

- Result: 6.7 TPS at 1 client and 6.3 at 64, within 6% of `expt_b0` at every client count.

expt_b6 - baseline design for workload B with half the synthetic data: SCALE 0.5 instead of 1

- Result: 10.2 TPS at 1 client and 9.2 at 64, 53% and 45% above `expt_b0`.

expt_b7 - workload B with all tenant tables colocated by merchant_id, query-matched indexes and fill factors

- Problem: The baseline distributes each table by its own id, so a merchant's customers, products, inventory, orders and items sit on unrelated shards and merchant-scoped transactions span workers.
- Optimisation: Distribute all tenant tables by `merchant_id` in one colocation group with composite keys, replace the indexes with ones matched to the queries, set fill factors that allow HOT updates, and drop `BEGIN`/`COMMIT` around single-statement transactions.
- Result: 8.6 TPS at 1 client and 11.2 at 64 with no serialization failures, but T3 still takes 2.0 s and is 88% of total latency at 1 client.

expt_b8 - expt_b7 with T3 routed to one worker by adding merchant_id to its join

- Problem: T3's join of `orders` and `order_items` omits `merchant_id`, so Citus cannot route it to one worker.
- Optimisation: Add `merchant_id` to T3's join, `IS DISTINCT FROM` guards to T5 and T8 so unchanged rows are not rewritten, and `merchant_id` to T1's final `UPDATE orders`.
- Result: T3 falls from 2,040 ms to 1.4 ms at 1 client and throughput rises to 62.4 TPS at 1 client and 230.2 at 64 (7x and 20x `expt_b7`), leaving T7 as 97% of latency at 64 clients.

expt_b9 - expt_b8 with T1 rewritten as one set-based statement

- Problem: T1 sends up to 26 statements per order (about 18 on average), each a separate round trip through the coordinator.
- Optimisation: Rewrite T1 as one statement of chained CTEs that checks stock, reserves it and inserts the order and its items together.
- Result: T1 got slower at 1 client (10.2 to 19.1 ms) and throughput barely moved (59.0 TPS at 1 client, 239.8 at 64), since T7 still dominates.

expt_b10 - expt_b9 with T7 routed through a product-to-merchant lookup table

- Problem: T7 does not name `merchant_id`, so each of its six statements goes to all 32 inventory shards, and at 64 clients about 62 of the 64 clients are inside T7.
- Optimisation: Add a `product_merchant_map` table, distributed by `product_id`, so T7 looks up each product's merchant and then debits and credits with single-shard `UPDATE`s.
- Result: T7 falls from 861 to 9.0 ms at 64 clients and throughput rises to 118.6 TPS at 1 client and 367.1 at 64, after which T5 (1,554 ms at 64 clients) caps throughput.

expt_b11 - expt_b10 with T5 routed through an order-to-merchant lookup table

- Problem: T5 updates `orders` by `order_id` alone, so it goes to all 32 shards and saturates at about 36 TPS, capping overall throughput near 366 TPS.
- Optimisation: Add an `order_merchant_map` table, distributed by `order_id` and written by T1 for each new order, so T5 looks up the merchant and updates one shard.
- Result: T5 falls from 1,554 to 28.5 ms at 64 clients, but throughput only rises to 123.6 TPS at 1 client and 405.2 at 64, because T6 now caps it at 65% of latency.

expt_b12 - expt_b11 with T6 answered from a per-merchant daily sales rollup

- Problem: T6 re-aggregates about 411,000 orders for its 30-day window on every call and takes 1,030 ms at 64 clients.
- Optimisation: Add a per-merchant, per-day `merchant_daily_sales` rollup, colocated with `orders` and updated by T1 in the same transaction, so T6 reads the rollup for whole days and `orders` only for the boundary day.
- Result: T6 falls from 1,030 to 245 ms at 64 clients and throughput reaches 165.9 TPS at 1 client, a peak of 1,519.7 at 8 and 1,098.7 at 64.

expt_b13 - expt_b12 with T1 as a distributed function delegated to the merchant's worker

- Problem: Citus runs T1's CTE statement as a series of separate distributed subplans through the coordinator, so T1 takes 21.7 ms at 1 client against about 1.2 ms for single-shard transactions.
- Optimisation: Move T1 into a distributed function, `place_order`, which Citus delegates whole to the worker holding the merchant's shards.
- Result: T1 falls from 21.7 to 10.1 ms at 1 client and throughput rises to 207.0 TPS at 1 client and 1,237.6 at 64, with T6 now the largest share of latency.

expt_b14 - expt_b13 with 8 shards per table instead of 32

- Problem: T6 is 39 to 51% of latency and runs as 32 shard tasks whose fixed per-task overhead outweighs the under 1,000 rows each one reads.
- Optimisation: Create every distributed table with 8 shards (2 per worker) instead of Citus's default 32.
- Result: T6 falls from 263 to 109 ms at 64 clients and throughput rises to 250.2 TPS at 1 client, 3,188.6 at 16 and 2,434.3 at 64, about twice `expt_b13` at 64.

expt_b15 - expt_b14 with 4 shards per table, one per worker

- Problem: With 8 shards, T6 still runs two tasks on every worker.
- Optimisation: Use 4 shards, one per worker.
- Result: T6 falls from 109 to 28 ms at 64 clients and throughput rises to 263.1 TPS at 1 client and 3,897.1 at 64 (1.6x `expt_b14`), leaving T7 as the largest share of latency.

expt_b16 - expt_b15 with T7's transfer as a distributed function (not carried forward)

- Problem: T7 sends six statements in sequence through the coordinator (4.6 ms at 1 client), two-thirds of all statements the coordinator handles, and the coordinator is the suspected bottleneck.
- Optimisation: Move T7's debit and credit into a distributed function, `transfer_inventory`, delegated to the source merchant's worker.
- Result: Throughput fell to 208.9 TPS at 1 client and 2,672.9 at 64 (from 263.1 and 3,897.1), because the delegated worker opens a new, uncached connection for every credit on another worker.

expt_b17 - expt_b15 with the product-to-merchant lookup table as a reference table

- Problem: Each of T7's two lookups in `product_merchant_map` is a round trip from the coordinator to a worker.
- Optimisation: Make `product_merchant_map` a reference table and register the coordinator in Citus's metadata, so the lookups read a local copy on the coordinator.
- Result: T7 falls from 4.6 to 3.0 ms and throughput rises to 321.4 TPS at 1 client, but from 8 clients up it is below `expt_b15` (3,820.1 against 3,897.1 at 64), likely because the lookups now use coordinator CPU.

expt_b18 - expt_b15 with T7's two lookups merged into one statement

- Problem: T7's two lookups are independent but run one after the other.
- Optimisation: Merge them into one statement on the still-sharded `product_merchant_map`.
- Result: T7 is 9 to 13% faster at every client count, and throughput rises 3% at 1 client (270.9 TPS) and 0.6% at 64 (3,920.0).

expt_b19 - expt_b15 with the lookup table as a reference table and T7's two lookups merged into one

- Problem: The reference-table lookups of `expt_b17` cost coordinator CPU for two statements per T7.
- Optimisation: Combine `expt_b17`'s reference table with `expt_b18`'s merged lookup, so T7 makes one local lookup on the coordinator.
- Result: 279.5 TPS at 1 client and 4,020.7 at 64, above `expt_b15` and `expt_b18` at every client count, though 7,649 transactions needed a retry at 64 clients, mostly T1's rollup upsert.

expt_b20 - expt_b19 with REPEATABLE READ instead of SERIALIZABLE

- Problem: Retries grow with throughput, and `SERIALIZABLE` also pays for tracking every read to detect read/write conflicts.
- Optimisation: Lower every node's isolation level from `SERIALIZABLE` to `REPEATABLE READ`, which still detects write-write conflicts.
- Result: Throughput rises 5% at 1 client (294.2 TPS) and 2% at 64 (4,098.5), the best at 64 clients, retries and serialization failures at 64 clients did not fall (7,924 and 181, against 7,649 and 141).

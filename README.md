expt_a0 - performance of baseline design as a function of number of clients for workload A

expt_a7 - workload A with all tenant tables colocated by merchant_id, query-matched indexes and fill factors

- Problem: The baseline distributes each table by its own id, so a merchant's customers, products, inventory, orders and items sit on unrelated shards and merchant-scoped transactions span workers; at 1 client T3 averages 2.6 s and T4 479 ms, together 94% of latency.
- Optimisation: Distribute all tenant tables by `merchant_id` in one colocation group with composite keys, replace the indexes with ones matched to the queries, set fill factors that allow HOT updates, and drop `BEGIN`/`COMMIT` around single-statement transactions.
- Result: 4.3 TPS at 1 client, a peak of 4.8 at 32 and 4.1 at 64 with no serialization failures, but T3 still takes 2.5 s and is 95% of total latency at 1 client.

expt_a8 - expt_a7 with T3 routed to one worker by adding merchant_id to its join

- Problem: T3's join of `orders` and `order_items` omits `merchant_id`, so Citus cannot route it to one worker, and it takes 2,459 ms at 1 client.
- Optimisation: Add `merchant_id` to T3's join, `IS DISTINCT FROM` guards to T5 and T8 so unchanged rows are not rewritten, and `merchant_id` to T1's final `UPDATE orders`.
- Result: T3 falls from 2,459 ms to 1.3 ms at 1 client and throughput rises to 113.7 TPS at 1 client and 334.6 at 64 (26x and 81x `expt_a7`), but from 4 clients up most clients aborted during the run on a T1 commit error pgbench does not retry (2 of 4, 7 of 8, 15 of 16, 30 of 32 and 61 of 64), and T5 is 79% of latency at 64 clients.

expt_a9 - expt_a8 with T1 rewritten as one set-based statement

- Problem: T1 sends up to 26 statements per order (about 18 on average), each a separate round trip through the coordinator, and at 9.5 ms it is 39% of latency at 1 client.
- Optimisation: Rewrite T1 as one statement of chained CTEs that checks stock, reserves it and inserts the order and its items together.
- Result: On a different node set from `expt_a8`, T1 got slower at 1 client (9.5 to 16.8 ms) and throughput fell to 89.1 TPS at 1 client while reaching 337.2 at 64 with no aborted clients, where T5 (1,557 ms) is 82% of latency.

expt_a10 - expt_a9 with T7 routed through a product-to-merchant lookup table

- Problem: T7 does not name `merchant_id`, so each of its six statements goes to all 32 inventory shards, and it takes 30.4 ms at 1 client and 202 ms at 64 clients.
- Optimisation: Add a `product_merchant_map` table, distributed by `product_id`, so T7 looks up each product's merchant and then debits and credits with single-shard `UPDATE`s.
- Result: T7 falls from 202 to 10.2 ms at 64 clients and throughput rises to 100.1 TPS at 1 client and 379.0 at 64, where one client aborted on a T7 commit error pgbench does not retry and T5 (1,411 ms, 85% of latency) caps throughput.

expt_a11 - expt_a10 with T5 routed through an order-to-merchant lookup table

- Problem: T5 updates `orders` by `order_id` alone, so it goes to all 32 shards and saturates at about 38 TPS from 8 clients up, capping overall throughput near 380 TPS.
- Optimisation: Add an `order_merchant_map` table, distributed by `order_id` and written by T1 for each new order, so T5 looks up the merchant and updates one shard.
- Result: T5 falls from 1,411 to 21.9 ms at 64 clients and throughput rises to 106.4 TPS at 1 client, a peak of 424.6 at 16 and 412.4 at 64, where two clients aborted on a T7 commit error pgbench does not retry, with T1 (56%) and T6 (36%) now most of the latency.

expt_a12 - expt_a11 with T6 answered from a per-merchant daily sales rollup

- Problem: T6 re-aggregates every order in its 30-day window on every call and takes 1,113 ms at 64 clients, 36% of latency.
- Optimisation: Add a per-merchant, per-day `merchant_daily_sales` rollup, colocated with `orders` and updated by T1 in the same transaction, so T6 reads the rollup for whole days and `orders` only for the boundary day.
- Result: T6 falls from 1,113 to 77.8 ms at 64 clients and throughput reaches 116.4 TPS at 1 client, a peak of 655.5 at 16 and 572.1 at 64, leaving T1 as 80% of latency at 1 client and 92% at 64.

expt_a13 - expt_a12 with T1 as a distributed function delegated to the merchant's worker

- Problem: Citus runs T1's CTE statement as a series of separate distributed subplans through the coordinator, so T1 takes 19.2 ms at 1 client against about 1 ms for single-shard transactions.
- Optimisation: Move T1 into a distributed function, `place_order`, which Citus delegates whole to the worker holding the merchant's shards.
- Result: T1 falls from 19.2 to 10.4 ms at 1 client and throughput rises to 181.2 TPS at 1 client, a peak of 1,123.9 at 8 and 930.9 at 64, with T1 still the largest share of latency (62 to 68%) and T6 next (15 to 26%).

expt_a14 - expt_a13 with 8 shards per table instead of 32

- Problem: T6 is 15 to 26% of latency and runs as 32 shard tasks whose fixed per-task overhead outweighs the roughly 1,000 rows each one reads.
- Optimisation: Create every distributed table with 8 shards (2 per worker) instead of Citus's default 32.
- Result: T6 falls from 307 to 136 ms at 64 clients and throughput rises to 196.2 TPS at 1 client, a peak of 1,721.9 at 16 and 1,461.5 at 64, 1.6x `expt_a13` at 64.

expt_a15 - expt_a14 with 4 shards per table, one per worker

- Problem: With 8 shards, T6 still runs two tasks on every worker and takes 136 ms at 64 clients.
- Optimisation: Use 4 shards, one per worker.
- Result: T6 falls from 136 to 76 ms at 64 clients and throughput is 203.0 TPS at 1 client, a peak of 1,693.2 at 16 and 1,573.9 at 64: within 4% of `expt_a14` up to 16 clients and 6 to 8% above it at 32 and 64, though two clients aborted at 64 when a worker's host name failed to resolve, and T1 remains 73 to 78% of latency.

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
- Result: 9.2 TPS at 1 client and 11.3 at 64 with no serialization failures, but T3 still takes 1.9 s and is 86% of total latency at 1 client.

expt_b8 - expt_b7 with T3 routed to one worker by adding merchant_id to its join

- Problem: T3's join of `orders` and `order_items` omits `merchant_id`, so Citus cannot route it to one worker.
- Optimisation: Add `merchant_id` to T3's join, `IS DISTINCT FROM` guards to T5 and T8 so unchanged rows are not rewritten, and `merchant_id` to T1's final `UPDATE orders`.
- Result: T3 falls from 1,873 ms to 1.4 ms at 1 client and throughput rises to 61.6 TPS at 1 client and 237.1 at 64 (7x and 21x `expt_b7`), leaving T7 as 97% of latency at 64 clients.

expt_b9 - expt_b8 with T1 rewritten as one set-based statement

- Problem: T1 sends up to 26 statements per order (about 18 on average), each a separate round trip through the coordinator.
- Optimisation: Rewrite T1 as one statement of chained CTEs that checks stock, reserves it and inserts the order and its items together.
- Result: T1 got slower at 1 client (10.3 to 19.2 ms) and throughput barely moved (58.4 TPS at 1 client, 233.2 at 64), since T7 still dominates.

expt_b10 - expt_b9 with T7 routed through a product-to-merchant lookup table

- Problem: T7 does not name `merchant_id`, so each of its six statements goes to all 32 inventory shards, and at 64 clients about 62 of the 64 clients are inside T7.
- Optimisation: Add a `product_merchant_map` table, distributed by `product_id`, so T7 looks up each product's merchant and then debits and credits with single-shard `UPDATE`s.
- Result: T7 falls from 885 to 9.0 ms at 64 clients and throughput rises to 116.4 TPS at 1 client and 364.5 at 64, after which T5 (1,562 ms at 64 clients) caps throughput.

expt_b11 - expt_b10 with T5 routed through an order-to-merchant lookup table

- Problem: T5 updates `orders` by `order_id` alone, so it goes to all 32 shards and saturates at about 36 TPS, capping overall throughput near 363 TPS.
- Optimisation: Add an `order_merchant_map` table, distributed by `order_id` and written by T1 for each new order, so T5 looks up the merchant and updates one shard.
- Result: T5 falls from 1,562 to 28.6 ms at 64 clients, but throughput only rises to 122.9 TPS at 1 client and 398.9 at 64, because T6 now caps it at 66% of latency.

expt_b12 - expt_b11 with T6 answered from a per-merchant daily sales rollup

- Problem: T6 re-aggregates about 411,000 orders for its 30-day window on every call and takes 1,067 ms at 64 clients.
- Optimisation: Add a per-merchant, per-day `merchant_daily_sales` rollup, colocated with `orders` and updated by T1 in the same transaction, so T6 reads the rollup for whole days and `orders` only for the boundary day.
- Result: T6 falls from 1,067 to 245 ms at 64 clients and throughput reaches 165.9 TPS at 1 client, a peak of 1,519.7 at 8 and 1,098.7 at 64.

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

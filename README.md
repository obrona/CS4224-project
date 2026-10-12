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

expt_b20 - replicate of expt_b19, the final design

- Problem: `expt_b19` ran once, and runs in different periods have differed by up to 5.5%, so the final design needs a measure of run-to-run variation.
- Optimisation: None; `run.sh`, `transactions/` and `explain/` are identical to `expt_b19`'s. It runs first in the partitioning batch (`partitioning_b19/README.md`).
- Result: 277.0 TPS at 1 client and 4,036.7 at 64, within 1% of `expt_b19` at every client count.

expt_b21 - replicate of expt_b19, the final design

- Problem: As `expt_b20`; a second replicate shows drift during the batch.
- Optimisation: None; identical to `expt_b19`. It runs last in the partitioning batch.
- Result: 276.0 TPS at 1 client and 4,060.1 at 64. The three runs of the final design (`expt_b19`, `expt_b20`, `expt_b21`) differ by at most 1.7% at any client count and show no drift across the batch, so differences of more than a few percent within the batch are not run-to-run noise.

expt_b22 - expt_b19 with products and inventory distributed by product_id (not carried forward)

- Problem: T7 (30% of workload B) is given product ids only, so under `merchant_id` it needs a lookup to find each row's merchant.
- Optimisation: Distribute `products` and `inventory` by `product_id` in their own colocation group, so T7 updates by `product_id` with no lookup; T1 then spans workers and is `expt_b8`'s non-delegated T1.
- Result: T7 falls from 3.7 to 3.1 ms at 1 client, but the non-delegated T1 rises from 10.4 to 13.3 ms at 1 client and from 37 to 88 ms at 64, and retries at 64 clients rise from 7,649 to 12,458. Throughput is 268.0 TPS at 1 client and 3,133.9 at 64 (4% and 22% below `expt_b19`), with a peak of 3,308.6 at 32.

expt_b23 - expt_b19 with orders and order_items distributed by order_id (not carried forward)

- Problem: T5 is given an order id only and needs `order_merchant_map`, which every T1 writes on a second worker.
- Optimisation: Distribute `orders` and `order_items` by `order_id`, so T5 is routed directly and the map is gone; T3 now asks every shard.
- Result: Throughput falls to 198.2 TPS at 1 client and 2,043.9 at 64 (29% and 49% below `expt_b19`). With `orders` no longer colocated with `merchant_daily_sales`, Citus runs T6 as two distributed subplans through the coordinator, and T6 rises from 8.6 to 21.2 ms at 1 client and from 32 to 224 ms at 64 (71% of latency). T5 also gets slower (1.7 to 3.7 ms at 1 client), because `orders`' primary key still leads with `merchant_id` and finding an order by `order_id` takes one index search per merchant (1,001 in `explain.log`). T3 rises only from 1.4 to 1.8 ms.

expt_b24 - expt_b19 with products and inventory as colocated single-shard tables (not carried forward)

- Problem: T7 needs a lookup, and its two updates commit across two workers three times in four.
- Optimisation: Make `products` and `inventory` single-shard tables in one colocation group, so T7 needs no lookup and commits on one worker; every catalog access goes to that worker.
- Result: T7 falls from 3.7 to 2.4 ms at 1 client, and throughput is 287.6 TPS at 1 client, 3% above `expt_b19` and the best 1-client result under `SERIALIZABLE`. From 16 clients up it is 13 to 17% below (3,348.2 at 64), because the non-delegated T1 rises from 37 to 85 ms at 64 clients and retries from 7,649 to 13,873. T2, T4 and T9, which now all go to one worker, are at most 1.7 ms slower at 64 clients, so most of the loss comes from T1.
- The first run (job 930969) failed loading `inventory` because of a Citus 14.1.0 bug with `INSERT ... SELECT` between single-shard tables. `inventory` is now loaded from `generate_series`, which gives the same rows, and the results are from job 933678.

expt_b25 - expt_b19 with inventory as a reference table (not carried forward)

- Problem: T7 needs a lookup to find each product's merchant.
- Optimisation: Make `inventory` a reference table with a copy on every node, so T7 needs no lookup; every inventory write then goes to all 5 nodes.
- Result: Throughput falls to 210.8 TPS at 1 client (25% below `expt_b19`), peaks at 351.7 at 4 clients and falls to 302.3 at 64 (93% below). At 64 clients, T1, T2 and T7, the three transactions that write `inventory`, take 413 to 444 ms each, against 5 to 37 ms in `expt_b19`. This is consistent with writes to the replicated table running one at a time across the cluster.

expt_b26 - expt_b19 with REPEATABLE READ instead of SERIALIZABLE (not carried forward)

- Problem: Retries grow with throughput, and `SERIALIZABLE` also pays for tracking every read to detect read/write conflicts.
- Optimisation: Lower every node's isolation level from `SERIALIZABLE` to `REPEATABLE READ`, which still detects write-write conflicts.
- Result: Throughput rises 5% at 1 client (294.2 TPS) and 2% at 64 (4,098.5), the best at 64 clients, retries and serialization failures at 64 clients did not fall (7,924 and 181, against 7,649 and 141).
- Not carried forward: the gain is within run-to-run noise, and `REPEATABLE READ` allows a read-only anomaly within a node (T4 can see T9's new price without a concurrent T1's stock change for the same product) that `SERIALIZABLE` prevents. Ran as `expt_b20` (job 887306) and was renumbered.

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

-- Workload A: optimisations specific to A (all branch from expt_a15) --

expt_a15_1 - replicate of expt_a15

- Result: 199.9 TPS at 1 client and 1,730.7 at 64, mean 1,287.6, with every point valid; 5.7% above `expt_a15`, which ran in an earlier batch.

expt_a15_2 - replicate of expt_a15

- Result: 198.0 TPS at 1 client and 1,755.3 at 64, mean 1,286.7: within 0.07% of `expt_a15_1` in mean TPS and 1.4% at any client count. `expt_a16` to `expt_a19` are compared with the mean of the two, 1,287.2.

expt_a16 - expt_a15 without T5 routing, so T1 writes no order-map row

- Problem: T1 is 73 to 75% of latency in `expt_a15`, and its row in `order_merchant_map` lies on another worker three times in four, so most orders commit on two nodes.
- Optimisation: Drop `order_merchant_map`: T1 no longer inserts a map row, and T5 returns to `expt_a10`'s all-shard update, now over 4 shards.
- Result: T1 falls from 10.3 to 4.1 ms and throughput rises to 342.3 TPS at 1 client, but T5 takes 280.6 ms at 64 clients (90% of latency) and caps throughput at 2,059 to 2,135 TPS from 8 clients; mean 1,662.0, 1.29x the replicates.

-- Final Design (workload A) --

expt_a17 - expt_a15 with order IDs chosen so that T1's map row lies on the merchant's worker

- Problem: As for `expt_a16`: T1's map row usually forces a two-phase commit, but T5 still needs the map.
- Optimisation: Colocate `order_merchant_map` with the tenant tables and draw order IDs in a coordinator function, `next_colocated_order_id`, until the map row's shard is on the merchant's worker (four draws on average), so the delegated T1 commits on one node while T5 stays routed.
- Result: T1 falls from 10.3 to 4.6 ms at 1 client and from 73.2 to 31.5 ms at 64 while T5 is unchanged; 333.5 TPS at 1 client, a peak of 3,315.7 at 16 and 2,683.4 at 64, mean 2,256.5 (1.75x the replicates of `expt_a15`).

expt_a17_1 - replicate of expt_a17

- Result: 341.2 TPS at 1 client and 2,652.3 at 64, mean 2,195.5.

expt_a17_2 - replicate of expt_a17

- Result: 342.6 TPS at 1 client and 2,663.1 at 64, mean 2,197.5. The three runs of the final design (`expt_a17`, `expt_a17_1`, `expt_a17_2`) average 2,216.5 TPS and differ from that mean by at most 1.8% (5.7% at any client count, `expt_a17` at 8 clients).

expt_a15_3 - replicate of expt_a15, control for the batch of expt_a17_1, expt_a17_2 and expt_a42 to expt_a46

- Result: 188.0 TPS at 1 client and 1,737.7 at 64, mean 1,281.9: 0.4% below `expt_a15_1` and `expt_a15_2`, so the two batches agree.

-- Rejected optimisations for workload A --

expt_a18 - expt_a15 with each merchant-day rollup row split into 4 slots

- Problem: Concurrent T1s for a hot merchant upsert the same `merchant_daily_sales` row; about 31,000 transactions are retried at 64 clients in the replicates of `expt_a15`.
- Optimisation: Add `slot = order_id % 4` to the rollup's primary key, so concurrent orders for one merchant usually upsert different rows; T6 sums all slots and is unchanged.
- Result: Retries fall to 7,340 and serialization failures to 65 at 64 clients (from about 31,000 and 2,600), but T1 is no faster (76.2 against 73.2 ms) and T6 slows from 8.3 to 21.7 ms at 1 client and from 72.9 to 212.4 ms at 64; mean 1,068.1 TPS, 0.83x the replicates.

expt_a19 - expt_a15 with the changes of both expt_a17 and expt_a18

- Result: Mean 1,661.4 TPS, 0.74x `expt_a17`: the slots cut retries at 64 clients (6,129 against 24,049) without speeding up T1 (33.7 against 31.5 ms), and T6 takes 218.7 ms.

-- Shard count around the final design (workload A) --

expt_a42 - expt_a17 with 1 shard per table

- Result: Killed during the 1-client run when the PostgreSQL server on xcnf1, the only worker holding data, exceeded the job step's memory limit (Slurm oom_kill). The 1-client point is not valid (pgbench exit 2, 177.8 TPS) and no other client count ran.

expt_a43 - expt_a17 with 2 shards per table

- Result: 312.5 TPS at 1 client and 1,603.6 at 64 (8% and 40% below the final design), with a peak of 2,069.4 at 16: two of the four workers hold all the data. Mean 0.67x.

expt_a44 - expt_a17 with 8 shards per table

- Result: 311.6 TPS at 1 client and 1,608.2 at 64 (8% and 40% below), with a peak of 2,946.7 at 16; T6 takes 211.5 ms at 64 against 91.7. Mean 0.79x.

expt_a45 - expt_a17 with 16 shards per table

- Result: 271.4 TPS at 1 client and 1,279.7 at 64 (20% and 52% below), with a peak of 2,196.5 at 8; T6 takes 325.9 ms at 64. Mean 0.65x.

expt_a46 - expt_a17 with 32 shards per table

- Result: 244.0 TPS at 1 client and 967.5 at 64 (28% and 64% below), with a peak of 1,683.4 at 8; T6 takes 479.7 ms at 64. Mean 0.47x. Four shards, one per worker, remain the best count for the final design, as on workload B.

-- 2^4 ablation around expt_a17 (workload A) --

expt_a17_3 - replicate of expt_a17, control of ablation batch 1

- Result: 342.6 TPS at 1 client and 2,674.1 at 64, mean 2,219.7, with every point valid; the cells of batch 1 are compared with it.

expt_a17_4 - replicate of expt_a17, control of ablation batch 2

- Result: 338.1 TPS at 1 client and 2,648.7 at 64, mean 2,184.4, with every point valid; the cells of batch 2 are compared with it.

expt_a27 - expt_a17 with T5 routing off

- Result: 335.3 TPS at 1 client and 2,038.0 at 64 (98% and 76% of `expt_a17_3`), mean 1,620.2 (73%). At 64 clients T5 holds 90% of summed latency (283.9 ms per call). Every point is valid.

expt_a28 - expt_a17 with the T6 rollup off

- Result: 218.7 TPS at 1 client and 647.0 at 64 (64% and 24% of `expt_a17_3`), mean 520.9 (23%). At 64 clients T6 holds 71% of summed latency (1,406.0 ms per call). Every point is valid.

expt_a29 - expt_a17 with T7 routing off

- Result: 286.1 TPS at 1 client and 1,890.3 at 64 (84% and 71% of `expt_a17_3`), mean 1,466.9 (66%). At 64 clients T7 holds 90% of summed latency (603.8 ms per call). Every point is valid.

expt_a30 - expt_a17 with T1 delegation off

- Result: 186.3 TPS at 1 client and 1,183.0 at 64 (54% and 44% of `expt_a17_3`), mean 1,026.8 (46%). At 64 clients T1 holds 82% of summed latency (109.9 ms per call). Clients abort (pgbench exit 2) at 32 and 64 clients, so those points are invalid.

expt_a31 - expt_a17 with T5 routing and the T6 rollup off

- Result: 219.1 TPS at 1 client and 454.3 at 64 (64% and 17% of `expt_a17_3`), mean 414.7 (19%). At 64 clients T5 holds 91% of summed latency (1,269.8 ms per call). Every point is valid.

expt_a32 - expt_a17 with T5 routing and T7 routing off

- Result: 276.1 TPS at 1 client and 1,694.3 at 64 (81% and 63% of `expt_a17_3`), mean 1,310.6 (59%). At 64 clients T5 holds 86% of summed latency (324.1 ms per call). Every point is valid.

expt_a33 - expt_a17 with T5 routing and T1 delegation off

- Result: 185.6 TPS at 1 client and 1,344.2 at 64 (54% and 50% of `expt_a17_3`), mean 1,030.8 (46%). At 64 clients T5 holds 73% of summed latency (343.2 ms per call). Clients abort (pgbench exit 2) at 8, 16, 32 and 64 clients, so those points are invalid.

expt_a34 - expt_a17 with the T6 rollup and T7 routing off

- Result: 191.8 TPS at 1 client and 528.8 at 64 (56% and 20% of `expt_a17_3`), mean 450.5 (20%). At 64 clients T7 holds 84% of summed latency (2,030.8 ms per call). Every point is valid.

expt_a35 - expt_a17 with the T6 rollup and T1 delegation off

- Result: 142.6 TPS at 1 client and 394.9 at 64 (42% and 15% of `expt_a17_4`), mean 322.8 (15%). At 64 clients T6 holds 56% of summed latency (206.2 ms per call). Clients abort (pgbench exit 2) at 4, 8, 16, 32 and 64 clients, so those points are invalid.

expt_a36 - expt_a17 with T7 routing and T1 delegation off

- Result: 164.1 TPS at 1 client and 1,157.7 at 64 (49% and 44% of `expt_a17_4`), mean 914.4 (42%). At 64 clients T7 holds 77% of summed latency (830.8 ms per call). Clients abort (pgbench exit 2) at 16, 32 and 64 clients, so those points are invalid.

expt_a37 - expt_a17 with T5 routing, the T6 rollup and T7 routing off

- Result: 190.8 TPS at 1 client and 421.6 at 64 (56% and 16% of `expt_a17_4`), mean 383.6 (18%). At 64 clients T5 holds 89% of summed latency (1,348.2 ms per call). Every point is valid.

expt_a38 - expt_a17 with T5 routing, the T6 rollup and T1 delegation off

- Result: 149.7 TPS at 1 client and 276.6 at 64 (44% and 10% of `expt_a17_4`), mean 223.5 (10%). At 64 clients T5 holds 33% of summed latency (36.0 ms per call). Clients abort (pgbench exit 2) at 4, 8, 16, 32 and 64 clients, so those points are invalid.

expt_a39 - expt_a17 with T5 routing, T7 routing and T1 delegation off

- Result: 165.2 TPS at 1 client and 1,145.3 at 64 (49% and 43% of `expt_a17_4`), mean 908.4 (42%). At 64 clients T5 holds 61% of summed latency (337.3 ms per call). Clients abort (pgbench exit 2) at 16 and 64 clients, so those points are invalid.

expt_a40 - expt_a17 with the T6 rollup, T7 routing and T1 delegation off

- Result: 128.8 TPS at 1 client and 514.1 at 64 (38% and 19% of `expt_a17_4`), mean 345.0 (16%). At 64 clients T7 holds 74% of summed latency (1,189.4 ms per call). Clients abort (pgbench exit 2) at 4, 8, 16, 32 and 64 clients, so those points are invalid.

expt_a41 - expt_a17 with T5 routing, the T6 rollup, T7 routing and T1 delegation off

- Result: 129.7 TPS at 1 client and 198.3 at 64 (38% and 7% of `expt_a17_4`), mean 214.3 (10%). At 64 clients T5 holds 41% of summed latency (55.5 ms per call). Clients abort (pgbench exit 2) at 4, 8, 16, 32 and 64 clients, so those points are invalid.

expt_b0 - performance of baseline design as a function of number of clients for workload B

- Result: 6.7 TPS at 1 client, a peak of 7.8 at 16 and 6.4 at 64, with T3 averaging 1.9 s at 1 client.

expt_b1 - baseline design for workload B with 2 worker nodes instead of 4

- Result: 4.7 TPS at 1 client and 3.7 at 64, 30% and 42% below `expt_b0`.

expt_b2 - baseline design for workload B with stronger merchant skew: HOT_ORDER_PERCENT 80 instead of 50

- Result: 6.7 TPS at 1 client and 6.0 at 64, at most 6% below `expt_b0` at any client count.

expt_b3 - baseline design for workload B with twice the synthetic data: SCALE 2 instead of 1

- Result: 2.0 TPS at 1 client and 3.4 at 64, 70% and 47% below `expt_b0`, and the 1-client run has T7 stalls of up to 78 s.

expt_b4 - baseline design for workload B with 8 worker nodes instead of 4

- Result: 9.0 TPS at 1 client and 10.2 at 64, 35% and 59% above `expt_b0`.

expt_b5 - baseline design for workload B with HOT_ORDER_PERCENT 10 instead of 50

- Result: 6.7 TPS at 1 client and 6.3 at 64, within 6% of `expt_b0` at every client count.

expt_b6 - baseline design for workload B with half the synthetic data: SCALE 0.5 instead of 1

- Result: 10.2 TPS at 1 client and 9.2 at 64, 53% and 45% above `expt_b0`.

expt_b7 - workload B with all tenant tables colocated by merchant_id, query-matched indexes and fill factors

- Problem: The baseline distributes each table by its own id, so a merchant's customers, products, inventory, orders and items sit on unrelated shards and merchant-scoped transactions span workers.
- Optimisation: Distribute tenant tables by `merchant_id` in one colocation group with composite keys, replace the indexes with ones matched to the queries, set fill factors that allow HOT updates, and drop `BEGIN`/`COMMIT` around single-statement transactions.
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
- Optimisation: Add an `order_merchant_map` table, distributed by `order_id` and written by T1 for each new order, so T5 looks up the merchant and updates one shard. Route T1 to use 2PC to update order_merchant_map as well.
- Result: T5 falls from 1,562 to 28.6 ms at 64 clients, but throughput only rises to 122.9 TPS at 1 client and 398.9 at 64, as T6 caps it at 66% of latency.

expt_b12 - expt_b11 with T6 answered from a per-merchant daily sales rollup

- Problem: T6 re-aggregates about 411,000 orders for its 30-day window on every call and takes 1,067 ms at 64 clients.
- Optimisation: Add a per-merchant, per-day `merchant_daily_sales` rollup, colocated with `orders` and updated by T1 in the same transaction; T6 reads the rollup for whole days and `orders` only for the boundary day.
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
- Result: Throughput fell to 208.9 TPS at 1 client and 2,672.9 at 64 (from 263.1 and 3,897.1), because the delegated worker opens a new uncached connection for every credit on another worker.

expt_b17 - expt_b15 with the product-to-merchant lookup table as a reference table

- Problem: Each of T7's two lookups in `product_merchant_map` is a round trip from the coordinator to a worker.
- Optimisation: Make `product_merchant_map` a reference table and register the coordinator in Citus's metadata, thus making the lookups read a local copy on the coordinator.
- Result: T7 falls from 4.6 to 3.0 ms and throughput rises to 321.4 TPS at 1 client, but from 8 clients up it is below `expt_b15` (3,820.1 against 3,897.1 at 64), likely because the lookups now use coordinator CPU.

expt_b18 - expt_b15 with T7's two lookups merged into one statement

- Problem: T7's two lookups are independent but run one after the other.
- Optimisation: Merge them into one statement on `product_merchant_map`.
- Result: T7 is 9 to 13% faster at every client count, and throughput rises 3% at 1 client (270.9 TPS) and 0.6% at 64 (3,920.0).

-- Final Design --

expt_b19 - expt_b15 with the lookup table as a reference table and T7's two lookups merged into one

- Problem: The reference-table lookups of `expt_b17` cost coordinator CPU for two statements per T7.
- Optimisation: Combine `expt_b17`'s reference table with `expt_b18`'s merged lookup, so T7 makes one local lookup on the coordinator.
- Result: 279.5 TPS at 1 client and 4,020.7 at 64, above `expt_b15` and `expt_b18` at every client count, though 7,649 transactions needed a retry at 64 clients, mostly T1's rollup upsert.

expt_b20 - replicate of expt_b19

- Result: 277.0 TPS at 1 client and 4,036.7 at 64, within 1% of `expt_b19` at every client count.

expt_b21 - replicate of expt_b19

- Result: 276.0 TPS at 1 client and 4,060.1 at 64. The three runs of the final design (`expt_b19`, `expt_b20`, `expt_b21`) differ by at most 1.7% at any client count and show no drift across the batch.

-- Rejected Optimizations with different partitioning strategies / isolation levels --

expt_b22 - expt_b19 with products and inventory distributed by product_id

- Problem: T7 (30% of workload B) is given product ids only, so under `merchant_id` it needs a lookup to find each row's merchant.
- Optimisation: Distribute `products` and `inventory` by `product_id` in their own colocation group; T7 updates by `product_id` with no lookup, T1 spans workers and is `expt_b8`'s non-delegated T1.
- Result: T7 falls from 3.7 to 3.1 ms at 1 client, but the non-delegated T1 rises from 10.4 to 13.3 ms at 1 client and from 37 to 88 ms at 64, and retries at 64 clients rise from 7,649 to 12,458. Throughput is 268.0 TPS at 1 client and 3,133.9 at 64 (4% and 22% below `expt_b19`), with a peak of 3,308.6 at 32.

expt_b23 - expt_b19 with orders and order_items distributed by order_id

- Problem: T5 is given an order id only and needs `order_merchant_map`, which every T1 writes on a second worker.
- Optimisation: Distribute `orders` and `order_items` by `order_id`, so T5 is routed directly and the map is gone. T3 now also queries every shard.
- Result: Throughput falls to 198.2 TPS at 1 client and 2,043.9 at 64 (29% and 49% below `expt_b19`). With `orders` no longer colocated with `merchant_daily_sales`, Citus runs T6 as two distributed subplans through the coordinator, and T6 rises from 8.6 to 21.2 ms at 1 client and from 32 to 224 ms at 64 (71% of latency). T5 also gets slower (1.7 to 3.7 ms at 1 client), as `orders`' primary key still leads with `merchant_id` and finding an order by `order_id` takes one index search per merchant (1,001 in `explain.log`). T3 rises only from 1.4 to 1.8 ms.

expt_b24 - expt_b19 with products and inventory as colocated single-shard tables

- Problem: T7 needs a lookup, and its two updates commit across two workers three times in four.
- Optimisation: Make `products` and `inventory` single-shard tables in one colocation group, so T7 needs no lookup and commits on one worker; every catalog access goes to that worker.
- Result: T7 falls from 3.7 to 2.4 ms at 1 client, and throughput is 287.6 TPS at 1 client, 3% above `expt_b19`. From 16 clients up it is 13 to 17% below (3,348.2 at 64; the 16-client run crossed midnight for its last 464 s, which slows T6, and ran 3,259.3 TPS, 9% below, before it), because the non-delegated T1 rises from 37 to 85 ms at 64 clients and retries from 7,649 to 13,873. T2, T4 and T9, which now all go to one worker, are at most 1.7 ms slower at 64 clients, so most of the loss comes from T1.

expt_b25 - expt_b19 with inventory as a reference table

- Problem: T7 needs a lookup to find each product's merchant.
- Optimisation: Make `inventory` a reference table with a copy on every node, so T7 needs no lookup; every inventory write then goes to all 5 nodes.
- Result: Throughput falls to 210.8 TPS at 1 client (25% below `expt_b19`), peaks at 351.7 at 4 clients and falls to 302.3 at 64 (93% below). At 64 clients, T1, T2 and T7, the three transactions that write `inventory`, take 413 to 444 ms each, against 5 to 37 ms in `expt_b19`. This is consistent with writes to the replicated table running one at a time across the cluster.

expt_b26 - expt_b19 with REPEATABLE READ instead of SERIALIZABLE

- Problem: Retries grow with throughput, and `SERIALIZABLE` also pays for tracking every read to detect read/write conflicts.
- Optimisation: Lower every node's isolation level from `SERIALIZABLE` to `REPEATABLE READ`, which still detects write-write conflicts.
- Result: Throughput rises 5% at 1 client (294.2 TPS) and 2% at 64 (4,098.5), the best at 64 clients, retries and serialization failures at 64 clients did not fall (7,924 and 181, against 7,649 and 141).
- Not carried forward as `REPEATABLE READ` allows a read-only anomaly within a node (T4 can see T9's new price without a concurrent T1's stock change for the same product) that `SERIALIZABLE` prevents.

-- 2^4 ablation around expt_b19 --

expt_b27 - expt_b19 with T5 routing off

- Result: 310.0 TPS at 1 client and 2,970.0 at 8, 11% and 6% above `expt_b19`, because T1 no longer writes `order_merchant_map` on a second worker (4.9 against 10.4 ms at 1 client). From 16 clients up, T5, sent to every `orders` shard, queues on Citus's lock for multi-shard modifications: it takes 192 ms at 64 clients and holds 57 of the 64 clients, and throughput is 2,960.2 (26% below). Retried transactions fall from 963 to 295 at 8 clients and from 7,649 to 352 at 64.

expt_b28 - expt_b19 with the T6 rollup off

- Result: 173.4 TPS at 1 client and 586.2 at 64 (38% and 85% below `expt_b19`). T6 scans `orders` again and takes 33.6 ms at 1 client and 942 ms at 64, where it holds 55 of the 64 clients.

expt_b29 - expt_b19 with T7 routing off

- Result: 129.1 TPS at 1 client and 583.6 at 64 (54% and 85% below). T7, back to six statements sent to every `inventory` shard, takes 17.5 ms at 1 client and 358 ms at 64, where it holds 63 of the 64 clients; throughput peaks at 752.3 at 8 clients and falls 22% by 64.

expt_b30 - expt_b19 with T1 delegation off

- Result: 264.2 TPS at 1 client (5% below) and 2,907.5 at 64 (28% below; not valid, 2 clients aborted). The multi-statement T1 takes 12.3 ms at 1 client and 82 ms at 64 (37 ms in `expt_b19`), holds 24 of the 64 clients, and retried transactions rise from 7,649 to 10,501.

expt_b31 - expt_b19 with T5 routing and the T6 rollup off

- Result: 208.0 TPS at 1 client and 527.2 at 64 (26% and 87% below). T5 holds 53 of the 64 clients at 1,014 ms, and T6 takes 166 ms.

expt_b32 - expt_b19 with T5 routing and T7 routing off

- Result: 135.3 TPS at 1 client and 613.4 at 64 (52% and 85% below), with a peak of 776.7 at 8 clients; T7 holds 63 of the 64 clients.

expt_b33 - expt_b19 with T5 routing and T1 delegation off

- Result: 257.5 TPS at 1 client and 2,631.2 at 64 (8% and 35% below; 1 client aborted at 16). As in `expt_b27`, T5 holds 54 of the 64 clients, at 206 ms.

expt_b34 - expt_b19 with the T6 rollup and T7 routing off

- Result: 114.7 TPS at 1 client and 308.8 at 64 (59% and 92% below), flat from 8 clients; T7 holds 62 of the 64 clients. With both the rollup and T7 routing off, mean TPS is 9.6 times lower than `expt_b19`'s.

expt_b35 - expt_b19 with the T6 rollup and T1 delegation off

- Result: 164.6 TPS at 1 client and 644.9 at 64 (41% and 84% below); T6 holds 51 of the 64 clients. Not valid from 16 clients up: 4, 5 and 9 clients aborted at 16, 32 and 64 when T1's commit failed.

expt_b36 - expt_b19 with T7 routing and T1 delegation off

- Result: 125.0 TPS at 1 client and 605.1 at 64 (55% and 85% below), with a peak of 765.0 at 8 clients; T7 holds 63 of the 64 clients.

expt_b37 - expt_b19 with T5 routing, the T6 rollup and T7 routing off

- Result: 124.3 TPS at 1 client and 313.3 at 64 (56% and 92% below), with a peak of 344.6 at 8 clients; T7 holds 62 of the 64 clients.

expt_b38 - expt_b19 with T5 routing, the T6 rollup and T1 delegation off

- Result: 172.0 TPS at 1 client (38% below). Not valid from 4 clients up: 2, 7, 14, 30 and 62 clients aborted at 4, 8, 16, 32 and 64 clients when T1's commit failed, so only 2 clients were left by the end of the 64-client run.

expt_b39 - expt_b19 with T5 routing, T7 routing and T1 delegation off

- Result: 123.9 TPS at 1 client and 676.6 at 64 (56% and 83% below), with a peak of 775.0 at 8 clients; T7 holds 63 of the 64 clients.

expt_b40 - expt_b19 with the T6 rollup, T7 routing and T1 delegation off

- Result: 110.7 TPS at 1 client and 327.6 at 64 (60% and 92% below); T7 holds 61 of the 64 clients. Unlike `expt_b35`, `expt_b38` and `expt_b41`, no client aborts, probably because T7 holds nearly all of them.

expt_b41 - expt_b19 with T5 routing, the T6 rollup, T7 routing and T1 delegation off

- Result: 109.5 TPS at 1 client, 61% below `expt_b19` and 1.8 times `expt_b8`'s 61.6, which ran the same four transactions on 32 shards. Not valid from 4 clients up: 2, 6, 14, 30 and 62 clients aborted at 4, 8, 16, 32 and 64 clients when T1's commit failed.

-- expt_b19 at 1, 2, 8, 16 and 32 shards --

expt_b42 - expt_b19 with 1 shard per table

- Result: 356.0 TPS at 1 client, 27% above `expt_b19` and the highest of any experiment. Every distributed table, `order_merchant_map` included, sits on xcnf18, so T1 commits on one node (2.6 against 10.4 ms) and so does T7 (2.6 against 3.7 ms); T6 runs as one task and takes 13.0 against 8.6 ms. The other three workers hold nothing: throughput peaks at 1,548.2 at 8 clients and is 1,447.3 at 64 (64% below).

expt_b43 - expt_b19 with 2 shards per table

- Result: 1,612.4 TPS at 4 clients, 23% above `expt_b19`, but 2,361.6 at 64 (41% below), with a peak of 2,415.9 at 32: two of the four workers hold all the tenant data. 259.3 TPS at 1 client (7% below).

expt_b44 - expt_b19 with 8 shards per table

- Result: 5 to 8% below `expt_b19` up to 16 clients (peak 3,353.1), then 2,537.9 at 64 (37% below). T6 runs 8 tasks and takes 111 ms at 64 clients, against 32 ms.

expt_b45 - expt_b19 with 16 shards per table

- Result: 236.1 TPS at 1 client and 2,081.3 at 64 (16% and 48% below), with a peak of 2,783.1 at 16. T6 takes 14.6 ms at 1 client and 173 ms at 64.

expt_b46 - expt_b19 with 32 shards per table

- Result: 215.8 TPS at 1 client and 1,269.9 at 64 (23% and 68% below). Throughput peaks at 1,997.3 at 8 clients and dips to 1,236.2 at 16, as `expt_b13` did with 32 shards. T6 takes 19.4 ms at 1 client and 272 ms at 64.

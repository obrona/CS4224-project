# Workload A Optimization Ideas

## Summary

Workload A is dominated by short merchant-scoped transactions: T1–T4 alone contribute 76% of executions. The baseline distributes tables by unrelated surrogate IDs, causing T1 and T3 to touch multiple shards unnecessarily. The best strategy is therefore:

1. Remove avoidable SQL round trips.
2. Co-locate each merchant’s data.
3. Optimize T1 and T3 specifically.
4. Reduce contention and retry overhead.
5. Address expensive T6 reporting separately.

Citus recommends distributing on the column most frequently used for filtering and joining; co-located tenant data permits single-worker execution instead of cross-node communication. [Citus multitenant guidance](https://learn.microsoft.com/en-us/postgresql/citus/tutorial-multi-tenant?view=citus-14)

## Optimization Ideas

### O1 — Remove unnecessary `BEGIN` and `COMMIT`

**Premise:** T2, T3, T4, T5, T6, T8, and T9 each contain only one SQL statement but explicitly execute `BEGIN`, the statement, and `COMMIT`.

**Why it could work:** A single PostgreSQL statement is already atomic under autocommit. Removing the explicit transaction commands reduces each execution from three client/server exchanges to one. These transactions constitute 59% of Workload A.

**What needs to be done:**

- Remove `BEGIN` and `COMMIT` from all single-statement transaction scripts.
- Keep explicit transactions for multi-statement T1 and T7.
- Verify that pgbench still counts each script execution as one transaction.
- Benchmark this independently because it is small, low-risk, and potentially high-impact.

---

### O2 — Distribute and co-locate tables by `merchant_id`

**Premise:** T1, T2, T3, T4, T8, and T9 operate on one merchant, but the baseline distributes every table using a different entity ID. Consequently, one merchant’s customer, products, inventory, orders, and order items can reside on many shards.

**Why it could work:** Distributing all tenant tables by `merchant_id` lets Citus route a merchant-scoped query or transaction to one shard. Joins and writes for T1, T3, and T4 can then execute on one worker without repartition joins or multi-shard transaction coordination. Citus specifically identifies distribution-column filtering and co-located joins as major performance factors. [Citus performance guidance](https://learn.microsoft.com/en-us/postgresql/citus/performance-tuning?view=citus-14)

**What needs to be done:**

- Distribute `customers`, `products`, `inventory`, `orders`, and `order_items` on `merchant_id`.
- Explicitly place them in the same colocation group using `colocate_with`.
- Make primary and unique constraints include the distribution column, for example `(merchant_id, order_id)`.
- Include `merchant_id` in every join, lookup, update, and delete predicate.
- Make `merchants` a reference table, or distribute it on `merchant_id` if reference replication is unnecessary.
- For T5, supply or derive the merchant for the chosen initial order so the update includes both `merchant_id` and `order_id`; otherwise Citus must search every shard.
- Preserve T7 as a distributed transaction when its source and destination belong to different merchants.

---

### O3 — Replace T1’s repeated statements with one set-based function

**Premise:** T1 is 36% of Workload A and currently performs several statements per item: product validation, price retrieval, inventory reservation, sequence allocation, and item insertion. With up to five items, one order causes many client/coordinator/worker exchanges.

**Why it could work:** A database function can perform the whole order placement using one client call. Set-based processing can read prices, validate stock, reserve inventory, and insert all items together. This reduces parsing, planning, network latency, and distributed transaction setup.

**What needs to be done:**

- Create a function accepting `merchant_id`, `customer_id`, arrays of product IDs and quantities, and the requested item count.
- Route the function using `merchant_id` and co-locate it with the merchant tables.
- Validate the customer and all products before creating the order.
- Aggregate repeated product IDs before checking and decrementing inventory.
- Lock inventory rows in sorted product-ID order.
- Use `UPDATE ... RETURNING` to confirm that every required reservation succeeded.
- Insert the order and all order items with `INSERT ... SELECT`.
- Compute the order total inside SQL from the captured prices.
- Raise an exception or return a clear failure result so the entire operation rolls back when any item is invalid or understocked.
- Handle ID generation explicitly. One possible design is one sequence call for the order and deterministic item IDs derived from `(order_id, line_number)`, eliminating one sequence round trip per item.

---

### O4 — Add workload-specific composite indexes and correct T3

**Premise:** The baseline has only single-column `merchant_id` indexes. They do not efficiently support T3’s merchant/customer/order-time filtering or its order-to-items join.

**Why it could work:** A B-tree matching equality filters followed by `created_at DESC` can find recent orders without scanning and sorting all orders for the merchant. PostgreSQL can use B-tree indexes to satisfy ordering directly. [PostgreSQL index documentation](https://www.postgresql.org/docs/18/indexes.html)

**What needs to be done:**

- Add an orders index such as:
  `orders (merchant_id, customer_id, created_at DESC, order_id)`.
- Add an order-items index:
  `order_items (merchant_id, order_id)`.
- Ensure product lookup has:
  `products (merchant_id, product_id)` and
  `inventory (merchant_id, product_id)`.
- Rewrite T3 to select the 20 most recent **orders in a subquery first**, then join those orders to their items.
- Treat this as both a performance and correctness fix: the current query limits the joined item rows to 20, rather than returning the items belonging to the 20 most recent orders.
- Avoid including frequently updated `quantity`, `updated_at`, or `order_status` columns in indexes, since that would increase update cost and prevent HOT updates.

---

### O5 — Reduce serialization failures and deadlocks

**Premise:** The benchmark defaults every transaction to `SERIALIZABLE`. T1, T2, and T7 update inventory concurrently, while hot merchants receive 50% of orders. This can create serialization retries and deadlocks that reduce successful TPS.

**Why it could work:** The inventory updates already use atomic arithmetic and predicates such as `quantity >= requested_quantity`. These protect the non-negative inventory invariant without necessarily requiring serializable isolation. Consistent lock ordering also prevents transactions from acquiring the same inventory rows in opposite orders.

**What needs to be done:**

- Benchmark `READ COMMITTED` against the serializable baseline.
- Keep conditional atomic updates and database check constraints.
- In T1 and T7, lock/update inventory rows in ascending `(merchant_id, inventory_id)` order.
- For T7, lock both rows before changing either quantity.
- Validate after each run that no inventory quantity is negative and that committed transfers conserve total inventory.
- Report the change in serialization failures, deadlocks, retries, and TPS.
- Retain `SERIALIZABLE` if the required application semantics demand a globally serializable history; do not select isolation solely from TPS.

---

### O6 — Optimize T6 global sales reporting

**Premise:** T6 is only 5% of the mix, but every execution scans and aggregates recent orders across the cluster. A slow 5% transaction can still occupy pgbench clients long enough to limit overall TPS.

**Why it could work:** The aggregation groups by `merchant_id`, which becomes the distribution column under O2. Workers can compute merchant totals locally and return small partial results. An appropriate time index or summary table can further reduce rows scanned.

**What needs to be done:**

1. First test a normal index such as:
   `orders (created_at, merchant_id) INCLUDE (total_amount)`.
2. Run `EXPLAIN (ANALYZE, BUFFERS)` to confirm that it is selective enough for the 30-day window.
3. If T6 remains dominant, introduce a daily merchant-sales summary distributed by `merchant_id`.
4. Populate it from historical orders during data loading.
5. Update it transactionally when T1 successfully creates an order.
6. To preserve exact timestamp semantics, use summaries only for complete calendar days and scan base orders for the two partial boundary days.
7. Compare the T6 gain against additional T1 write contention; do not automatically retain the summary if overall TPS falls.

---

### O7 — Enable HOT updates through table fill factors

**Premise:** `inventory` is updated by T1, T2, and T7, while `orders.order_status` is updated by T5. The initial bulk load can leave heap pages full, making each update create a tuple on another page and increasing index and vacuum work.

**Why it could work:** Lower fill factors leave room for new tuple versions on the same page. Because the frequently changed columns are deliberately excluded from indexes, PostgreSQL can often perform HOT updates.

**What needs to be done:**

- Create `inventory` with an initial fill factor around 70–80.
- Create `orders` with an initial fill factor around 80–90.
- Load the data after applying these settings.
- Keep `quantity`, `updated_at`, and `order_status` out of secondary indexes unless measurements prove otherwise.
- Inspect `n_tup_hot_upd`, dead tuples, WAL volume, and TPS.
- Tune autovacuum only if the ten-minute measured runs accumulate enough dead tuples to affect results.

---

### O8 — Use prepared-query mode

**Premise:** The baseline sets `PGBENCH_QUERY_MODE=simple`, so frequently repeated statements incur recurring parse and planning work.

**Why it could work:** Prepared mode allows PostgreSQL/Citus to reuse prepared statements, which is valuable for short, repetitive OLTP queries where planning is a meaningful part of latency.

**What needs to be done:**

- Run an experiment with `PGBENCH_QUERY_MODE=prepared`.
- Ensure all pgbench variables are passed as values rather than changing SQL structure unnecessarily.
- Check whether generic plans still perform correct single-shard routing.
- Compare per-transaction latency, coordinator CPU use, and TPS.
- Test this both before and after the stored-function rewrite because O3 may reduce its marginal benefit.

---

### O9 — Tune Citus connection settings and shard count

**Premise:** The baseline uses 32 default shards and `citus.max_adaptive_executor_pool_size=4`. Most optimized Workload A operations will be short single-shard queries, while T6 remains multi-shard.

**Why it could work:** Large executor pools add connection overhead to short transactional queries. Citus recommends values around 1–2 for short OLTP operations, while shard count must balance parallelism against planning and connection overhead. [Citus tuning guidance](https://learn.microsoft.com/en-us/postgresql/citus/performance-tuning?view=citus-14)

**What needs to be done:**

- Test adaptive executor pool sizes 1, 2, and 4.
- Test `citus.executor_slow_start_interval` near 100 ms for OLTP-heavy versions.
- Compare 32 and 64 explicitly co-located shards; keep all related tables on the same shard count.
- Confirm that hot merchants are reasonably distributed across the four workers.
- Record worker connection counts, coordinator CPU, worker CPU, and T6 latency.
- Keep `max_connections`, shared-pool sizes, and `work_mem` within actual node memory limits; `32MB × many connections × parallel tasks` can overcommit memory.

## Recommended Experiment Order

1. **V0:** unchanged baseline.
2. **V1:** O1, removal of redundant transaction commands.
3. **V2:** O2, merchant distribution and explicit colocation.
4. **V3:** O4, targeted indexes and corrected T3.
5. **V4:** O3, set-based T1 function and reduced ID allocation.
6. **V5:** O5 and O7, isolation/lock ordering and HOT-update tuning.
7. **V6:** O6, selected T6 optimization.
8. **V7:** tune O8 and O9 on the final design.

For every version, use identical hardware, scale, seeds, workload weights, resets, warmup, duration, and client counts. Run each important configuration at least three times and report median TPS along with per-transaction latency, retries, serialization failures, and deadlocks.

## Assumptions

- Transaction correctness and inventory constraints must be preserved.
- Durability-weakening shortcuts such as `fsync=off`, unlogged transactional tables, or `synchronous_commit=off` are excluded from the primary design.
- T3 should return the items belonging to the 20 most recent orders, as stated in the project description.
- Merchant colocation is the primary design direction; T6 and cross-merchant T7 are accepted as the minority distributed operations.

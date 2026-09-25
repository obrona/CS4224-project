### Optimisation 2: Route T5 by order ID

Added `order_route(order_id, merchant_id)`, distributed by `order_id`. The data
loader copies the mapping from the actual `orders` rows after each reset.
T1 inserts a mapping for each new order in the same transaction as the order
and its items. T5 first looks up the merchant, then updates `orders` using
`(merchant_id, order_id)` so Citus can target one merchant shard. A missing
order remains a no-op. The extra T1 write and distributed commit cost must be
included when comparing overall workload A throughput.

### Optimisation 3: Route T7 by product ID

Added `inventory_locator(product_id, merchant_id, inventory_id)`, distributed
by `product_id` and populated from the actual `inventory` rows after each
reset. T7 looks up each product on its locator shard and includes both
`merchant_id` and `inventory_id` in each inventory update. It still rolls
back the debit if the credit fails. Equal source and destination IDs skip
the lookups and transaction entirely; missing products or insufficient stock
also leave inventory unchanged.

The locator's primary key enforces one inventory record per product ID across
merchants. This matches the generated workload A data and makes T7's
product-ID-only input unambiguous. Loading data with duplicate product IDs
under different merchants will fail explicitly.

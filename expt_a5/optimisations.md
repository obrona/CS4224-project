### Previous experiment: expt_a3

### Optimisation 1: Route T5 by order ID

Added `order_route(order_id, merchant_id)`, a locator table distributed by
`order_id`. Its primary key makes each order ID map to one merchant. During
setup and after a data reset, `run.sh` populates the locator from the actual
`orders` rows using `\copy` through the coordinator.

T1 now inserts the locator row in the same SQL statement and transaction as
the new order and its items. The final `INSERT ... SELECT` reads from
`inserted_order`, so failed validation or reservation produces no order ID
and no locator row.

In expt_a3, T5 filters `orders` only by `order_id`. Since `orders` is
distributed by `merchant_id`, Citus cannot use that predicate to target a
merchant shard. In expt_a5, T5 first looks up `merchant_id` in
`order_route` by `order_id`, then updates `orders` using both
`merchant_id` and `order_id`. A missing locator row leaves the update as
a no-op.

The expected gain is lower T5 update cost from targeting one merchant shard.
The tradeoff is a locator lookup in T5, an additional distributed write in
T1, and locator storage and load time.
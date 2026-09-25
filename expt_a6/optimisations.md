### Prev: expt a5

### Optimisation: Route T7 inventory transfers by product ID

Added `product_route(product_id, inventory_id, merchant_id)` with a primary key
on `product_id`, distributed by that key. During data generation, `run.sh`
loads it from the actual `inventory` rows through the coordinator, and clears
it whenever the generated data is reset. The locator records the inventory
row and merchant for each product; inventory identity and ownership do not
change in this workload.

T7 first looks up each product in `product_route`, so Citus can target one
locator shard per product. It then uses the returned `merchant_id` together
with `inventory_id` and `product_id` in the debit and credit predicates. Since
`inventory` is distributed by `merchant_id`, each update can target only the
source or destination merchant shard. A missing locator row or failed debit
still rolls back the transfer.

The expected benefit is avoiding scatter/gather inventory lookups and
multi-shard updates. The cost is two locator reads per transfer, extra table
storage, and an additional load during setup. The debit and credit may still
involve two distinct inventory shards when the merchants differ.

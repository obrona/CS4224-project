### Prev: expt a7

### Optimisation: Execute T1 place order on the merchant's worker

T1 now calls `public.place_order_on_merchant`, a PL/pgSQL function installed by
`run.sh` after the tables are distributed. The function is registered with
`create_distributed_function` using `p_merchant_id` as its distribution
argument and `public.merchants` as its colocation table. Citus uses the
merchant ID supplied by T1 to choose the worker holding that merchant's
`merchants` shard.

The `customers`, `products`, `inventory`, `orders`, and `order_items`
tables are all distributed by `merchant_id` and colocated with `merchants`.
On the selected worker, the function validates the customer and requested
products, checks and reserves stock, calculates the total, and inserts the order
and its items. Duplicate product selections are combined before stock is
reserved. The function returns the new order ID, or zero if validation or
reservation prevents the order.

**Expected benefit.** The merchant-local work executes where the relevant
shards reside. This can reduce coordinator planning and orchestration of the
multi-step order operation and avoid sending intermediate results between the
coordinator and worker. It can also reduce cross-node traffic when several
tables are involved in the same order.

**Remaining costs.** The coordinator still allocates globally unique order
and item IDs from its sequences before the transaction. T1 also inserts into
`order_route` through the coordinator because that table is distributed by
`order_id`, not `merchant_id`. The function call and route insert remain in
one transaction, so a failed transaction rolls back both. Sequence values
consumed by a failed order are not reused. The extra SQL round trips and the
route-table write may offset the worker-local savings; compare T1 latency and
throughput against expt a7 before claiming an improvement.

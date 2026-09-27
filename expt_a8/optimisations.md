# A8: route T1 work to one worker

A7 T1 had seven distributed subplans and multiple INSERT ... SELECT steps that
pulled rows to the coordinator. A8 replaces that statement with the
public.a8_place_order function in functions/place_order_function.sql. Citus routes it
by merchant_id to the worker holding the colocated orders shard. The function
checks the customer and products, locks each distinct inventory row in product
ID order, validates combined quantities for duplicate selections, then updates
stock and inserts the order and items. It returns false without writing rows
when validation fails. A later error aborts the transaction and rolls back
the stock update and inserts.

The order and item sequences are coordinator-local, so T1 allocates their
IDs on the coordinator and passes them to the worker. On success, the
function also inserts the order_route row. This table is distributed by
order_id, so its shard may be on another worker and this is still a
distributed transaction. Unsuccessful orders can consume sequence values;
gaps are harmless.

run.sh creates and registers the function after distributing the schema.
Compare A8 against A7 using the same scale, seed, client counts, and
isolation settings. Track successful TPS, T1 latency, and retry/failure
counts. The net throughput gain is unmeasured until A8 runs on Citus.

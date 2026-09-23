\if :DEBUG_MODE
\set order_id :DEBUG_ORDER_ID
\set status_roll :DEBUG_STATUS_ROLL
\else
\set order_id random(1, :INITIAL_NUM_ORDERS)
\set status_roll random(1, 3)
\endif

-- T5 is given an order id, but orders is sharded by merchant_id.
-- order_merchant_map is sharded by order_id, so this lookup is routed to a
-- single shard. No transaction writes the map, and T5 owns no open
-- transaction here, so reading it as its own statement is safe.
SELECT COALESCE(MAX(merchant_id), 0) AS merchant_id
FROM order_merchant_map
WHERE order_id = (:order_id)::bigint
\gset t5_

\if :t5_merchant_id = 0
-- Fallback when the order is missing from the map: the un-routed UPDATE from
-- expt_b4, which is sent to every orders shard.
\if :status_roll = 1
UPDATE orders
SET order_status = 'PENDING'::text
WHERE order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'PENDING'::text;
\elif :status_roll = 2
UPDATE orders
SET order_status = 'SHIPPED'::text
WHERE order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'SHIPPED'::text;
\else
UPDATE orders
SET order_status = 'COMPLETED'::text
WHERE order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'COMPLETED'::text;
\endif

\else
-- Routed path. Naming merchant_id sends the UPDATE to one shard and gives
-- PostgreSQL the complete PRIMARY KEY (merchant_id, order_id).
\if :status_roll = 1
UPDATE orders
SET order_status = 'PENDING'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'PENDING'::text;
\elif :status_roll = 2
UPDATE orders
SET order_status = 'SHIPPED'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'SHIPPED'::text;
\else
UPDATE orders
SET order_status = 'COMPLETED'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'COMPLETED'::text;
\endif
\endif

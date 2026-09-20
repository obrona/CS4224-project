\if :DEBUG_MODE
\set order_id :DEBUG_ORDER_ID
\set status_roll :DEBUG_STATUS_ROLL
\else
\set order_id random(1, :INITIAL_NUM_ORDERS)
\set status_roll random(1, 3)
\endif

-- order_merchant_map is distributed by order_id, so this lookup is routed to a
-- single shard. It is filled once at data-load time and never written during
-- the run. order_id is its primary key, so the aggregate always yields one row
-- requires.
SELECT COALESCE(MAX(merchant_id), 0) AS merchant_id
FROM order_merchant_map
WHERE order_id = (:order_id)::bigint
\gset t5_

\if :t5_merchant_id > 0

-- Routed: merchant_id is known, so the UPDATE goes to a single shard.
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

\else

-- Fallback: the order is not in the map, so
-- update it without a merchant_id (searches every shard).
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

\endif

\if :DEBUG_MODE
\set order_id :DEBUG_ORDER_ID
\set status_roll :DEBUG_STATUS_ROLL
\else
\set order_id random(1, :INITIAL_NUM_ORDERS)
\set status_roll random(1, 3)
\endif

-- Look up the tenant by globally unique order ID, then route the update to
-- its merchant shard. A missing order remains a no-op.
SELECT COUNT(*) AS found, MAX(merchant_id) AS merchant_id
FROM order_route
WHERE order_id = (:order_id)::bigint
\gset t5_

\if :t5_found
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

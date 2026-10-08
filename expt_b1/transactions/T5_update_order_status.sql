\if :DEBUG_MODE
\set order_id :DEBUG_ORDER_ID
\set status_roll :DEBUG_STATUS_ROLL
\else
\set order_id random(1, :INITIAL_NUM_ORDERS)
\set status_roll random(1, 3)
\endif

BEGIN;

\if :status_roll = 1
UPDATE orders
SET order_status = 'PENDING'::text
WHERE order_id = (:order_id)::bigint;
\elif :status_roll = 2
UPDATE orders
SET order_status = 'SHIPPED'::text
WHERE order_id = (:order_id)::bigint;
\else
UPDATE orders
SET order_status = 'COMPLETED'::text
WHERE order_id = (:order_id)::bigint;
\endif

COMMIT;

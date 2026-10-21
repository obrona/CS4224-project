\if :DEBUG_MODE
\set merchant_id :DEBUG_MERCHANT_ID
\else
\set merchant_id CASE WHEN random(1, 100) <= :HOT_ORDER_PERCENT THEN random(1, :HOT_MERCHANTS) ELSE random((:HOT_MERCHANTS + 1), :NUM_MERCHANTS) END
\endif

\if :DEBUG_MODE
\set customer_id :DEBUG_CUSTOMER_ID
\else
\set customer_slot random(0, ((:NUM_CUSTOMERS - :merchant_id) / :NUM_MERCHANTS))
\set customer_id :merchant_id + (:customer_slot * :NUM_MERCHANTS)
\endif

BEGIN;

SELECT
  o.order_id,
  o.order_status,
  o.total_amount,
  o.created_at,
  oi.product_id,
  oi.quantity,
  oi.unit_price
FROM orders AS o
JOIN order_items AS oi
  ON oi.order_id = o.order_id
WHERE o.merchant_id = (:merchant_id)::bigint
  AND o.customer_id = (:customer_id)::bigint
ORDER BY o.created_at DESC
LIMIT 20;

COMMIT;

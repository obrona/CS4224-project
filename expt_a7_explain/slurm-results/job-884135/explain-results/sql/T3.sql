\set ON_ERROR_STOP on
BEGIN;
\echo T3 statement 1
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) SELECT
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
 AND oi.merchant_id = o.merchant_id
WHERE o.merchant_id = (:merchant_id)::bigint
  AND o.customer_id = (:customer_id)::bigint
ORDER BY o.created_at DESC
LIMIT 20;
ROLLBACK;

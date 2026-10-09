-- psql version of transactions/T3_order_history.sql for EXPLAIN only
\set merchant_id 1

SELECT customer_id
FROM orders
WHERE merchant_id = (:merchant_id)::bigint
ORDER BY order_id
LIMIT 1
\gset

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
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

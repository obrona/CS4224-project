\set ON_ERROR_STOP on
BEGIN;
\echo T4 statement 1
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) SELECT
  p.product_id,
  p.product_name,
  p.category,
  p.price,
  i.quantity
FROM products AS p
JOIN inventory AS i
  ON i.product_id = p.product_id
 AND i.merchant_id = p.merchant_id
WHERE p.merchant_id = (:merchant_id)::bigint
  AND p.product_id = (:product_id)::bigint;
ROLLBACK;

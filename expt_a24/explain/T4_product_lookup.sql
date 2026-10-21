-- psql version of transactions/T4_product_lookup.sql for EXPLAIN only
\set merchant_id 1

SELECT MIN(product_id) AS product_id
FROM products
WHERE merchant_id = (:merchant_id)::bigint
\gset

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT
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

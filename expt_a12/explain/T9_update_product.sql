-- psql version of transactions/T9_update_product.sql for EXPLAIN only
\set merchant_id 1
\set price_increase 5

SELECT MIN(product_id) AS product_id
FROM products
WHERE merchant_id = (:merchant_id)::bigint
\gset

BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
UPDATE products
SET price = price + (:price_increase)::numeric(12,2)
WHERE product_id = (:product_id)::bigint
  AND merchant_id = (:merchant_id)::bigint;

ROLLBACK;

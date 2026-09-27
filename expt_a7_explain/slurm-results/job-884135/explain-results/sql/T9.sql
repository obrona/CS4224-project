\set ON_ERROR_STOP on
BEGIN;
\echo T9 statement 1
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) UPDATE products
SET price = price + (:price_increase)::numeric(12,2)
WHERE product_id = (:product_id)::bigint
  AND merchant_id = (:merchant_id)::bigint;
ROLLBACK;

\set ON_ERROR_STOP on
BEGIN;
\echo T2 statement 1
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) UPDATE inventory
SET quantity = quantity + (:inventory_change)::integer,
    updated_at = CURRENT_TIMESTAMP
WHERE inventory_id = (:product_id)::bigint
  AND merchant_id = (:merchant_id)::bigint
  AND product_id = (:product_id)::bigint
  AND quantity + (:inventory_change)::integer >= 0;
ROLLBACK;

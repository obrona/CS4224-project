-- psql version of transactions/T2_update_inventory.sql for EXPLAIN only
\set merchant_id 1
\set inventory_change 5

SELECT MIN(product_id) AS product_id
FROM inventory
WHERE merchant_id = (:merchant_id)::bigint
\gset

BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
UPDATE inventory
SET quantity = quantity + (:inventory_change)::integer,
    updated_at = CURRENT_TIMESTAMP
WHERE inventory_id = (:product_id)::bigint
  AND merchant_id = (:merchant_id)::bigint
  AND product_id = (:product_id)::bigint
  AND quantity + (:inventory_change)::integer >= 0;

ROLLBACK;

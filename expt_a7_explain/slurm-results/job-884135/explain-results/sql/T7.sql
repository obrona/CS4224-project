\set ON_ERROR_STOP on
BEGIN;
SELECT inventory_id AS t7_source_inventory_id, merchant_id AS t7_source_merchant_id FROM product_route WHERE product_id = (:source_product_id)::bigint \gset
SELECT inventory_id AS t7_dest_inventory_id, merchant_id AS t7_dest_merchant_id FROM product_route WHERE product_id = (:dest_product_id)::bigint \gset
\echo T7 statement 1
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) SELECT COUNT(*) AS source_found,
       MAX(inventory_id) AS source_inventory_id,
       MAX(merchant_id) AS source_merchant_id
FROM product_route
WHERE product_id = (:source_product_id)::bigint;
\echo T7 statement 2
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) SELECT COUNT(*) AS dest_found,
       MAX(inventory_id) AS dest_inventory_id,
       MAX(merchant_id) AS dest_merchant_id
FROM product_route
WHERE product_id = (:dest_product_id)::bigint;
\echo T7 statement 3
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) WITH debit AS (
  UPDATE inventory
  SET quantity = quantity - (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = (:t7_source_merchant_id)::bigint
    AND inventory_id = (:t7_source_inventory_id)::bigint
    AND product_id = (:source_product_id)::bigint
    AND quantity >= (:transfer_qty)::integer
  RETURNING 1
)
SELECT EXISTS(SELECT 1 FROM debit) AS debit_ok;
\echo T7 statement 4
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) WITH credit AS (
  UPDATE inventory
  SET quantity = quantity + (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = (:t7_dest_merchant_id)::bigint
    AND inventory_id = (:t7_dest_inventory_id)::bigint
    AND product_id = (:dest_product_id)::bigint
  RETURNING 1
)
SELECT EXISTS(SELECT 1 FROM credit) AS credit_ok;
ROLLBACK;

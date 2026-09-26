-- psql version of transactions/T7_inventory_transfer.sql for EXPLAIN only
\set transfer_qty 1

SELECT MIN(product_id) AS source_product_id FROM products WHERE merchant_id = 1
\gset
SELECT MIN(product_id) AS dest_product_id FROM products WHERE merchant_id = 2
\gset

BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT EXISTS(
  SELECT 1 FROM inventory
  WHERE product_id = (:source_product_id)::bigint
) AS source_exists;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT EXISTS(
  SELECT 1 FROM inventory
  WHERE product_id = (:dest_product_id)::bigint
) AS dest_exists;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT inventory_id AS source_inventory_id FROM inventory WHERE product_id = (:source_product_id)::bigint;

SELECT inventory_id AS source_inventory_id FROM inventory WHERE product_id = (:source_product_id)::bigint
\gset

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT inventory_id AS dest_inventory_id FROM inventory WHERE product_id = (:dest_product_id)::bigint;

SELECT inventory_id AS dest_inventory_id FROM inventory WHERE product_id = (:dest_product_id)::bigint
\gset

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
WITH debit AS (
  UPDATE inventory
  SET quantity = quantity - (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:source_inventory_id)::bigint
    AND quantity >= (:transfer_qty)::integer
  RETURNING 1
)
SELECT EXISTS(SELECT 1 FROM debit) AS debit_ok;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
WITH credit AS (
  UPDATE inventory
  SET quantity = quantity + (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:dest_inventory_id)::bigint
  RETURNING 1
)
SELECT EXISTS(SELECT 1 FROM credit) AS credit_ok;

ROLLBACK;

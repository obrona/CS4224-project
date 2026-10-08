-- psql version of transactions/T7_inventory_transfer.sql for EXPLAIN only
\set transfer_qty 1

SELECT MIN(product_id) AS source_product_id FROM products WHERE merchant_id = 1
\gset
SELECT MIN(product_id) AS dest_product_id FROM products WHERE merchant_id = 2
\gset

-- product_merchant_map is a reference table. The lookup should run on the
-- coordinator's own copy, with no worker in the plan.
EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT COALESCE(MAX(merchant_id), 0) AS source_merchant_id
FROM product_merchant_map
WHERE product_id = (:source_product_id)::bigint;

SELECT COALESCE(MAX(merchant_id), 0) AS source_merchant_id
FROM product_merchant_map
WHERE product_id = (:source_product_id)::bigint
\gset t7_

SELECT COALESCE(MAX(merchant_id), 0) AS dest_merchant_id
FROM product_merchant_map
WHERE product_id = (:dest_product_id)::bigint
\gset t7_

BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
WITH debit AS (
  UPDATE inventory
  SET quantity = quantity - (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = (:t7_source_merchant_id)::bigint
    AND product_id = (:source_product_id)::bigint
    AND quantity >= (:transfer_qty)::integer
  RETURNING 1
)
SELECT EXISTS(SELECT 1 FROM debit) AS debit_ok;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
WITH credit AS (
  UPDATE inventory
  SET quantity = quantity + (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = (:t7_dest_merchant_id)::bigint
    AND product_id = (:dest_product_id)::bigint
  RETURNING 1
)
SELECT EXISTS(SELECT 1 FROM credit) AS credit_ok;

ROLLBACK;

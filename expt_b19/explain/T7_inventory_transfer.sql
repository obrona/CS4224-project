-- psql version of transactions/T7_inventory_transfer.sql for EXPLAIN only
\set transfer_qty 1

SELECT MIN(product_id) AS source_product_id FROM products WHERE merchant_id = 1
\gset
SELECT MIN(product_id) AS dest_product_id FROM products WHERE merchant_id = 2
\gset

-- product_merchant_map is a reference table. The lookup should run on the
-- coordinator's own copy, with no worker in the plan.
SELECT COALESCE(MAX(merchant_id) FILTER (WHERE product_id = (:source_product_id)::bigint), 0) AS source_merchant_id,
       COALESCE(MAX(merchant_id) FILTER (WHERE product_id = (:dest_product_id)::bigint), 0) AS dest_merchant_id
FROM product_merchant_map
WHERE product_id IN ((:source_product_id)::bigint, (:dest_product_id)::bigint)
\gset t7_

-- The plan shows the coordinator as the task's node whether the task ran
-- locally or over a connection to itself.
SET citus.log_local_commands = on;
EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT COALESCE(MAX(merchant_id) FILTER (WHERE product_id = (:source_product_id)::bigint), 0) AS source_merchant_id,
       COALESCE(MAX(merchant_id) FILTER (WHERE product_id = (:dest_product_id)::bigint), 0) AS dest_merchant_id
FROM product_merchant_map
WHERE product_id IN ((:source_product_id)::bigint, (:dest_product_id)::bigint);
RESET citus.log_local_commands;

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

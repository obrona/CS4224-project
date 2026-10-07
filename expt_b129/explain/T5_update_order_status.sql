-- psql version of transactions/T5_update_order_status.sql for EXPLAIN only
\set order_id 1

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT COALESCE(MAX(merchant_id), 0) AS merchant_id
FROM order_merchant_map
WHERE order_id = (:order_id)::bigint;

SELECT COALESCE(MAX(merchant_id), 0) AS merchant_id
FROM order_merchant_map
WHERE order_id = (:order_id)::bigint
\gset t5_

BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
UPDATE orders
SET order_status = 'SHIPPED'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'SHIPPED'::text;

ROLLBACK;

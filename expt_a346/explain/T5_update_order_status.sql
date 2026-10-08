-- psql version of transactions/T5_update_order_status.sql for EXPLAIN only
\set order_id 1

BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
UPDATE orders
SET order_status = 'SHIPPED'::text
WHERE order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'SHIPPED'::text;

ROLLBACK;

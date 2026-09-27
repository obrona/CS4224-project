\set ON_ERROR_STOP on
BEGIN;
SELECT merchant_id AS t5_merchant_id FROM order_route WHERE order_id = (:order_id)::bigint \gset
\echo T5 statement 1
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) SELECT COUNT(*) AS found, MAX(merchant_id) AS merchant_id
FROM order_route
WHERE order_id = (:order_id)::bigint;
\echo T5 statement 2
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) UPDATE orders
SET order_status = 'SHIPPED'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'SHIPPED'::text;
ROLLBACK;

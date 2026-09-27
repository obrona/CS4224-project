\set ON_ERROR_STOP on
BEGIN;
\echo T8 statement 1
EXPLAIN (ANALYZE, BUFFERS, VERBOSE, SETTINGS) UPDATE customers
SET email = 'Customer-' || :new_email_number || '@acme.com'
WHERE customer_id = (:customer_id)::bigint
  AND merchant_id = (:merchant_id)::bigint
  AND email IS DISTINCT FROM
      ('Customer-' || :new_email_number || '@acme.com');
ROLLBACK;

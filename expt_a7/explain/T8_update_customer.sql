-- psql version of transactions/T8_update_customer.sql for EXPLAIN only
\set merchant_id 1
\set new_email_number 424242

SELECT MIN(customer_id) AS customer_id
FROM customers
WHERE merchant_id = (:merchant_id)::bigint
\gset

BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
UPDATE customers
SET email = 'Customer-' || :new_email_number || '@acme.com'
WHERE customer_id = (:customer_id)::bigint
  AND merchant_id = (:merchant_id)::bigint;

ROLLBACK;

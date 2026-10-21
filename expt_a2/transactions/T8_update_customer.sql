
\if :DEBUG_MODE
\set merchant_id :DEBUG_MERCHANT_ID
\else
\set merchant_id random(1, :NUM_MERCHANTS)
\endif

\if :DEBUG_MODE
\set customer_id :DEBUG_CUSTOMER_ID
\set new_email_number :DEBUG_NEW_EMAIL_NUMBER
\else
\set customer_slot random(0, ((:NUM_CUSTOMERS - :merchant_id) / :NUM_MERCHANTS))
\set customer_id :merchant_id + (:customer_slot * :NUM_MERCHANTS)
\set new_email_number random(1, :NUM_CUSTOMERS)
\endif



BEGIN;

UPDATE customers
SET email = 'Customer-' || :new_email_number || '@acme.com'
WHERE customer_id = (:customer_id)::bigint
  AND merchant_id = (:merchant_id)::bigint;

COMMIT;

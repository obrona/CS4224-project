

\if :DEBUG_MODE
\set product_id :DEBUG_PRODUCT_ID
\else
\set product_id random(1, :NUM_PRODUCTS)
\endif

\set merchant_id  1 + ((:product_id - 1) % :NUM_MERCHANTS)
\set price_increase random(1, 10)

BEGIN;

UPDATE products
SET price = price + (:price_increase)::numeric(12,2)
WHERE product_id = (:product_id)::bigint
  AND merchant_id = (:merchant_id)::bigint;

COMMIT;

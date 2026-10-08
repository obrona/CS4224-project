-- psql version of transactions/T7_inventory_transfer.sql for EXPLAIN only
\set transfer_qty 1

SELECT MIN(product_id) AS source_product_id FROM products WHERE merchant_id = 1
\gset
SELECT MIN(product_id) AS dest_product_id FROM products WHERE merchant_id = 2
\gset

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

EXPLAIN (VERBOSE)
SELECT public.transfer_inventory(
  (:t7_source_merchant_id)::bigint,
  (:source_product_id)::bigint,
  (:t7_dest_merchant_id)::bigint,
  (:dest_product_id)::bigint,
  (:transfer_qty)::integer
);

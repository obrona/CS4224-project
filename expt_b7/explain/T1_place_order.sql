-- psql version of transactions/T1_place_order.sql for EXPLAIN only
\set merchant_id 1
\set item_count 3
\set qty_1 1
\set qty_2 1
\set qty_3 1
\set qty_4 1
\set qty_5 1

SELECT MIN(customer_id) AS customer_id
FROM customers
WHERE merchant_id = (:merchant_id)::bigint
\gset

SELECT
  p[1] AS product_id_1, p[2] AS product_id_2, p[3] AS product_id_3,
  p[4] AS product_id_4, p[5] AS product_id_5
FROM (
  SELECT array_agg(product_id ORDER BY product_id) AS p
  FROM (
    SELECT product_id FROM products
    WHERE merchant_id = (:merchant_id)::bigint
    ORDER BY product_id
    LIMIT 5
  ) AS first_products
) AS ids
\gset

-- No BEGIN / ROLLBACK here as T1 runs without a transaction block, and inside
-- one Citus would not delegate the call.

-- The id draw should run on the coordinator alone, with no Task.
EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT
  nextval('benchmark_order_id_seq') AS order_id,
  CASE WHEN (:item_count)::integer >= 1 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_1,
  CASE WHEN (:item_count)::integer >= 2 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_2,
  CASE WHEN (:item_count)::integer >= 3 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_3,
  CASE WHEN (:item_count)::integer >= 4 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_4,
  CASE WHEN (:item_count)::integer >= 5 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_5;

SELECT
  nextval('benchmark_order_id_seq') AS order_id,
  CASE WHEN (:item_count)::integer >= 1 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_1,
  CASE WHEN (:item_count)::integer >= 2 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_2,
  CASE WHEN (:item_count)::integer >= 3 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_3,
  CASE WHEN (:item_count)::integer >= 4 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_4,
  CASE WHEN (:item_count)::integer >= 5 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_5
\gset t1_

EXPLAIN (VERBOSE)
SELECT public.place_order(
  (:merchant_id)::bigint,
  (:customer_id)::bigint,
  (:t1_order_id)::bigint,
  (:item_count)::integer,
  ARRAY[(:product_id_1)::bigint, (:product_id_2)::bigint, (:product_id_3)::bigint,
        (:product_id_4)::bigint, (:product_id_5)::bigint],
  ARRAY[(:qty_1)::integer, (:qty_2)::integer, (:qty_3)::integer,
        (:qty_4)::integer, (:qty_5)::integer],
  ARRAY[(:t1_item_id_1)::bigint, (:t1_item_id_2)::bigint, (:t1_item_id_3)::bigint,
        (:t1_item_id_4)::bigint, (:t1_item_id_5)::bigint]
);

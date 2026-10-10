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

-- The success path for item_count = 3, one statement at a time. A statement
-- whose result a later one needs is explained, then run again with \gset.
-- The stock reservations are not run again: EXPLAIN ANALYZE already applied
-- them once, as the transaction does, and they only choose the branch.
BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT CASE WHEN EXISTS (
  SELECT customer_name, email
  FROM customers
  WHERE merchant_id = (:merchant_id)::bigint
    AND customer_id = (:customer_id)::bigint
) THEN 1 ELSE 0 END AS customer_ok;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT nextval('benchmark_order_id_seq') AS new_order_id;

SELECT nextval('benchmark_order_id_seq') AS new_order_id
\gset

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
INSERT INTO orders(
  order_id, merchant_id, customer_id, order_status, total_amount, created_at
)
VALUES(
  (:new_order_id)::bigint,
  (:merchant_id)::bigint,
  (:customer_id)::bigint,
  'PENDING'::text,
  0.00,
  CURRENT_TIMESTAMP
);

-- item 1
EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT
  CASE WHEN EXISTS (
    SELECT 1
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_1)::bigint
  ) THEN 1 ELSE 0 END AS product_ok,
  COALESCE((
    SELECT price
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_1)::bigint
    LIMIT 1
  ), 0.00)::numeric(12,2) AS price;

SELECT
  CASE WHEN EXISTS (
    SELECT 1
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_1)::bigint
  ) THEN 1 ELSE 0 END AS product_ok,
  COALESCE((
    SELECT price
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_1)::bigint
    LIMIT 1
  ), 0.00)::numeric(12,2) AS price
\gset item1_

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
WITH reserved AS (
  UPDATE inventory
  SET quantity = quantity - (:qty_1)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:product_id_1)::bigint
    AND merchant_id = (:merchant_id)::bigint
    AND product_id = (:product_id_1)::bigint
    AND quantity >= (:qty_1)::integer
  RETURNING 1
)
SELECT CASE WHEN EXISTS (SELECT 1 FROM reserved)
            THEN 1 ELSE 0 END AS stock_ok;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT nextval('benchmark_order_item_id_seq') AS order_item_id;

SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset item1_

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
INSERT INTO order_items(
  order_item_id, merchant_id, order_id, product_id, quantity, unit_price
)
VALUES(
  (:item1_order_item_id)::bigint,
  (:merchant_id)::bigint,
  (:new_order_id)::bigint,
  (:product_id_1)::bigint,
  (:qty_1)::integer,
  :item1_price
);

-- item 2
EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT
  CASE WHEN EXISTS (
    SELECT 1
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_2)::bigint
  ) THEN 1 ELSE 0 END AS product_ok,
  COALESCE((
    SELECT price
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_2)::bigint
    LIMIT 1
  ), 0.00)::numeric(12,2) AS price;

SELECT
  CASE WHEN EXISTS (
    SELECT 1
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_2)::bigint
  ) THEN 1 ELSE 0 END AS product_ok,
  COALESCE((
    SELECT price
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_2)::bigint
    LIMIT 1
  ), 0.00)::numeric(12,2) AS price
\gset item2_

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
WITH reserved AS (
  UPDATE inventory
  SET quantity = quantity - (:qty_2)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:product_id_2)::bigint
    AND merchant_id = (:merchant_id)::bigint
    AND product_id = (:product_id_2)::bigint
    AND quantity >= (:qty_2)::integer
  RETURNING 1
)
SELECT CASE WHEN EXISTS (SELECT 1 FROM reserved)
            THEN 1 ELSE 0 END AS stock_ok;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT nextval('benchmark_order_item_id_seq') AS order_item_id;

SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset item2_

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
INSERT INTO order_items(
  order_item_id, merchant_id, order_id, product_id, quantity, unit_price
)
VALUES(
  (:item2_order_item_id)::bigint,
  (:merchant_id)::bigint,
  (:new_order_id)::bigint,
  (:product_id_2)::bigint,
  (:qty_2)::integer,
  :item2_price
);

-- item 3
EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT
  CASE WHEN EXISTS (
    SELECT 1
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_3)::bigint
  ) THEN 1 ELSE 0 END AS product_ok,
  COALESCE((
    SELECT price
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_3)::bigint
    LIMIT 1
  ), 0.00)::numeric(12,2) AS price;

SELECT
  CASE WHEN EXISTS (
    SELECT 1
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_3)::bigint
  ) THEN 1 ELSE 0 END AS product_ok,
  COALESCE((
    SELECT price
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_3)::bigint
    LIMIT 1
  ), 0.00)::numeric(12,2) AS price
\gset item3_

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
WITH reserved AS (
  UPDATE inventory
  SET quantity = quantity - (:qty_3)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:product_id_3)::bigint
    AND merchant_id = (:merchant_id)::bigint
    AND product_id = (:product_id_3)::bigint
    AND quantity >= (:qty_3)::integer
  RETURNING 1
)
SELECT CASE WHEN EXISTS (SELECT 1 FROM reserved)
            THEN 1 ELSE 0 END AS stock_ok;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT nextval('benchmark_order_item_id_seq') AS order_item_id;

SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset item3_

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
INSERT INTO order_items(
  order_item_id, merchant_id, order_id, product_id, quantity, unit_price
)
VALUES(
  (:item3_order_item_id)::bigint,
  (:merchant_id)::bigint,
  (:new_order_id)::bigint,
  (:product_id_3)::bigint,
  (:qty_3)::integer,
  :item3_price
);

-- pgbench sums order_total with \set; psql's \set cannot do arithmetic.
SELECT (:qty_1) * (:item1_price) + (:qty_2) * (:item2_price)
     + (:qty_3) * (:item3_price) AS order_total
\gset

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
UPDATE orders
SET total_amount = (:order_total)::numeric(12,2)
WHERE order_id = (:new_order_id)::bigint;

ROLLBACK;

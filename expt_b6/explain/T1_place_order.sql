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

BEGIN;

EXPLAIN (VERBOSE)
WITH
input_items(item_no, product_id, quantity) AS (
  VALUES
    (1, (:product_id_1)::bigint, (:qty_1)::integer),
    (2, (:product_id_2)::bigint, (:qty_2)::integer),
    (3, (:product_id_3)::bigint, (:qty_3)::integer),
    (4, (:product_id_4)::bigint, (:qty_4)::integer),
    (5, (:product_id_5)::bigint, (:qty_5)::integer)
),
requested_items AS MATERIALIZED (
  SELECT item_no, product_id, quantity
  FROM input_items
  WHERE item_no <= (:item_count)::integer
),
requirements AS MATERIALIZED (
  SELECT product_id, SUM(quantity)::integer AS quantity
  FROM requested_items
  GROUP BY product_id
),
eligible AS MATERIALIZED (
  SELECT
    EXISTS (
      SELECT 1
      FROM customers c
      WHERE c.merchant_id = (:merchant_id)::bigint
        AND c.customer_id = (:customer_id)::bigint
    )
    AND NOT EXISTS (
      SELECT 1
      FROM requirements r
      LEFT JOIN products p
        ON p.merchant_id = (:merchant_id)::bigint
       AND p.product_id = r.product_id
      LEFT JOIN inventory i
        ON i.merchant_id = (:merchant_id)::bigint
       AND i.product_id = r.product_id
      WHERE p.product_id IS NULL
         OR i.product_id IS NULL
         OR i.quantity < r.quantity
    ) AS ok
),
reserved AS (
  UPDATE inventory i
  SET quantity = i.quantity - r.quantity,
      updated_at = CURRENT_TIMESTAMP
  FROM requirements r, eligible e
  WHERE e.ok
    AND i.merchant_id = (:merchant_id)::bigint
    AND i.product_id = r.product_id
  RETURNING i.product_id
),
reservation_ok AS MATERIALIZED (
  SELECT e.ok
     AND (SELECT COUNT(*) FROM reserved)
       = (SELECT COUNT(*) FROM requirements) AS ok
  FROM eligible e
),
inserted_order AS (
  INSERT INTO orders(
    order_id, merchant_id, customer_id, order_status, total_amount, created_at
  )
  SELECT
    nextval('benchmark_order_id_seq'),
    (:merchant_id)::bigint,
    (:customer_id)::bigint,
    'PENDING'::text,
    SUM(ri.quantity * p.price)::numeric(12,2),
    CURRENT_TIMESTAMP
  FROM requested_items ri
  JOIN products p
    ON p.merchant_id = (:merchant_id)::bigint
   AND p.product_id = ri.product_id
  CROSS JOIN reservation_ok ro
  WHERE ro.ok
  HAVING COUNT(*) = (:item_count)::integer
  RETURNING order_id, total_amount
),
inserted_items AS (
  INSERT INTO order_items(
    order_item_id, merchant_id, order_id, product_id, quantity, unit_price
  )
  SELECT
    nextval('benchmark_order_item_id_seq'),
    (:merchant_id)::bigint,
    o.order_id,
    ri.product_id,
    ri.quantity,
    p.price
  FROM requested_items ri
  JOIN products p
    ON p.merchant_id = (:merchant_id)::bigint
   AND p.product_id = ri.product_id
  CROSS JOIN inserted_order o
  RETURNING 1
)
SELECT
  EXISTS (SELECT 1 FROM inserted_order) AS order_created,
  (SELECT COUNT(*) FROM inserted_items) AS items_created,
  COALESCE((SELECT order_id FROM inserted_order), 0) AS new_order_id,
  COALESCE((SELECT total_amount FROM inserted_order), 0) AS new_order_total;

-- EXPLAIN does not return the new order's id or total, so the follow-up
-- writes use stand-ins; the plans do not depend on the values.
SELECT nextval('benchmark_order_id_seq') AS t1_new_order_id \gset
\set t1_new_order_total 10.00

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
INSERT INTO order_merchant_map (order_id, merchant_id)
VALUES ((:t1_new_order_id)::bigint, (:merchant_id)::bigint);

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
VALUES ((:merchant_id)::bigint, CURRENT_DATE, 1, (:t1_new_order_total)::numeric(12,2))
ON CONFLICT (merchant_id, sales_date)
DO UPDATE SET order_count = s.order_count + 1,
              revenue     = s.revenue + EXCLUDED.revenue;

ROLLBACK;

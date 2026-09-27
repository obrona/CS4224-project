\set ON_ERROR_STOP on
BEGIN;
\echo T1 planned statement (Citus does not support ANALYZE here)
EXPLAIN (VERBOSE, SETTINGS) WITH
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
-- Duplicate selections need their combined quantity reserved atomically.
requirements AS MATERIALIZED (
  SELECT product_id, SUM(quantity)::integer AS quantity
  FROM requested_items
  GROUP BY product_id
),
-- only eligible if all items requested exist.
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
  RETURNING order_id
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
-- If validation or reservation fails, inserted_order is empty and this inserts no route row.
-- All data-modifying CTEs complete as part of this statement.
INSERT INTO order_route (order_id, merchant_id)
SELECT o.order_id, (:merchant_id)::bigint
FROM inserted_order o;
\echo T1 actual execution time (psql Timing line follows)
\timing on
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
-- Duplicate selections need their combined quantity reserved atomically.
requirements AS MATERIALIZED (
  SELECT product_id, SUM(quantity)::integer AS quantity
  FROM requested_items
  GROUP BY product_id
),
-- only eligible if all items requested exist.
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
  RETURNING order_id
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
-- If validation or reservation fails, inserted_order is empty and this inserts no route row.
-- All data-modifying CTEs complete as part of this statement.
INSERT INTO order_route (order_id, merchant_id)
SELECT o.order_id, (:merchant_id)::bigint
FROM inserted_order o;
\timing off
ROLLBACK;

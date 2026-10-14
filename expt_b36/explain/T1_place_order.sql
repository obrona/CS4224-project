-- psql version of transactions/T1_place_order.sql (expt_b8's T1) for EXPLAIN only
\set merchant_id 1
\set qty_1 1

SELECT MIN(customer_id) AS customer_id
FROM customers
WHERE merchant_id = (:merchant_id)::bigint
\gset

SELECT MIN(product_id) AS product_id_1
FROM products
WHERE merchant_id = (:merchant_id)::bigint
\gset

-- T1 runs inside BEGIN/COMMIT. Reads are planned with ANALYZE; writes without
-- it, so the plan is recorded and nothing is changed.
BEGIN;

EXPLAIN (ANALYZE, VERBOSE, BUFFERS)
SELECT CASE WHEN EXISTS (
  SELECT customer_name, email
  FROM customers
  WHERE merchant_id = (:merchant_id)::bigint
    AND customer_id = (:customer_id)::bigint
) THEN 1 ELSE 0 END AS customer_ok;

SELECT nextval('benchmark_order_id_seq') AS new_order_id
\gset

EXPLAIN (VERBOSE)
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

EXPLAIN (VERBOSE)
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

SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset

EXPLAIN (VERBOSE)
INSERT INTO order_items(
  order_item_id, merchant_id, order_id, product_id, quantity, unit_price
)
VALUES(
  (:order_item_id)::bigint,
  (:merchant_id)::bigint,
  (:new_order_id)::bigint,
  (:product_id_1)::bigint,
  (:qty_1)::integer,
  1.00
);

EXPLAIN (VERBOSE)
UPDATE orders
SET total_amount = (1.00)::numeric(12,2)
WHERE merchant_id = (:merchant_id)::bigint
  AND order_id = (:new_order_id)::bigint;

EXPLAIN (VERBOSE)
INSERT INTO order_merchant_map (order_id, merchant_id)
VALUES ((:new_order_id)::bigint, (:merchant_id)::bigint);

EXPLAIN (VERBOSE)
INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
VALUES ((:merchant_id)::bigint, CURRENT_TIMESTAMP::date, 1, (1.00)::numeric(12,2))
ON CONFLICT (merchant_id, sales_date)
DO UPDATE SET order_count = s.order_count + 1,
              revenue     = s.revenue + EXCLUDED.revenue;

ROLLBACK;

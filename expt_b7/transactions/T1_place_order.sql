-- DEBUG_* variables have harmless defaults in run.sh, allowing CASE
-- expressions to replace pgbench's conditional meta-commands.
\set merchant_id CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_MERCHANT_ID ELSE CASE WHEN random(1, 100) <= :HOT_ORDER_PERCENT THEN random(1, :HOT_MERCHANTS) ELSE random((:HOT_MERCHANTS + 1), :NUM_MERCHANTS) END END
\set customer_slot random(0, ((:NUM_CUSTOMERS - :merchant_id) / :NUM_MERCHANTS))
\set customer_id CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_CUSTOMER_ID ELSE :merchant_id + (:customer_slot * :NUM_MERCHANTS) END
\set item_count CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_ITEM_COUNT ELSE random(:MIN_ITEMS_PER_ORDER, :MAX_ITEMS_PER_ORDER) END

-- Generate all five slots up front. requested_items retains only item_count.
\set product_slot_1 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_1 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_PRODUCT_ID_1 ELSE :merchant_id + (:product_slot_1 * :NUM_MERCHANTS) END
\set qty_1 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_QTY_1 ELSE random(:MIN_ORDER_QTY, :MAX_ORDER_QTY) END
\set product_slot_2 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_2 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_PRODUCT_ID_2 ELSE :merchant_id + (:product_slot_2 * :NUM_MERCHANTS) END
\set qty_2 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_QTY_2 ELSE random(:MIN_ORDER_QTY, :MAX_ORDER_QTY) END
\set product_slot_3 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_3 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_PRODUCT_ID_3 ELSE :merchant_id + (:product_slot_3 * :NUM_MERCHANTS) END
\set qty_3 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_QTY_3 ELSE random(:MIN_ORDER_QTY, :MAX_ORDER_QTY) END
\set product_slot_4 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_4 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_PRODUCT_ID_4 ELSE :merchant_id + (:product_slot_4 * :NUM_MERCHANTS) END
\set qty_4 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_QTY_4 ELSE random(:MIN_ORDER_QTY, :MAX_ORDER_QTY) END
\set product_slot_5 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_5 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_PRODUCT_ID_5 ELSE :merchant_id + (:product_slot_5 * :NUM_MERCHANTS) END
\set qty_5 CASE WHEN :DEBUG_MODE = 1 THEN :DEBUG_QTY_5 ELSE random(:MIN_ORDER_QTY, :MAX_ORDER_QTY) END

BEGIN;

-- Ids are drawn first, in a statement that reads no table, so it runs on the
-- coordinator alone (the sequences live there). The main statement then holds
-- only constants and can be routed to merchant_id's shard as one task.
-- As in expt_b0, one order id is drawn per T1, and item ids ascend with
-- item_no. CASE only evaluates nextval for the items this order has.
SELECT
  nextval('benchmark_order_id_seq') AS order_id,
  CASE WHEN (:item_count)::integer >= 1 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_1,
  CASE WHEN (:item_count)::integer >= 2 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_2,
  CASE WHEN (:item_count)::integer >= 3 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_3,
  CASE WHEN (:item_count)::integer >= 4 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_4,
  CASE WHEN (:item_count)::integer >= 5 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_5
\gset t1_

WITH
input_items(item_no, product_id, quantity, order_item_id) AS (
  VALUES
    (1, (:product_id_1)::bigint, (:qty_1)::integer, (:t1_item_id_1)::bigint),
    (2, (:product_id_2)::bigint, (:qty_2)::integer, (:t1_item_id_2)::bigint),
    (3, (:product_id_3)::bigint, (:qty_3)::integer, (:t1_item_id_3)::bigint),
    (4, (:product_id_4)::bigint, (:qty_4)::integer, (:t1_item_id_4)::bigint),
    (5, (:product_id_5)::bigint, (:qty_5)::integer, (:t1_item_id_5)::bigint)
),
requested_items AS MATERIALIZED (
  SELECT item_no, product_id, quantity, order_item_id
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
    (:t1_order_id)::bigint,
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
  RETURNING order_id, total_amount, created_at
),
inserted_items AS (
  INSERT INTO order_items(
    order_item_id, merchant_id, order_id, product_id, quantity, unit_price
  )
  SELECT
    ri.order_item_id,
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
),
-- Keep T6 rollup in step with orders, in the order's own created_at day.
-- No row when no order was inserted. Colocated with orders, so it stays on
-- the same shard.
rollup AS (
  INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
  SELECT (:merchant_id)::bigint, o.created_at::date, 1, o.total_amount
  FROM inserted_order o
  ON CONFLICT (merchant_id, sales_date)
  DO UPDATE SET order_count = s.order_count + 1,
                revenue     = s.revenue + EXCLUDED.revenue
  RETURNING 1
)
SELECT
  EXISTS (SELECT 1 FROM inserted_order) AS order_created,
  (SELECT COUNT(*) FROM inserted_items) AS items_created,
  (SELECT COUNT(*) FROM rollup) AS rollup_rows
\gset t1_

-- Keep order_merchant_map in step with orders. Sharded by order_id, so it
-- cannot join the statement above.
\if :t1_order_created
INSERT INTO order_merchant_map (order_id, merchant_id)
VALUES ((:t1_order_id)::bigint, (:merchant_id)::bigint);
\endif

COMMIT;

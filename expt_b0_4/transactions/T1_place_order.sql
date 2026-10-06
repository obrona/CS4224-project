\if :DEBUG_MODE
\set merchant_id :DEBUG_MERCHANT_ID
\else
\set merchant_id CASE WHEN random(1, 100) <= :HOT_ORDER_PERCENT THEN random(1, :HOT_MERCHANTS) ELSE random((:HOT_MERCHANTS + 1), :NUM_MERCHANTS) END
\endif

\if :DEBUG_MODE
\set customer_id :DEBUG_CUSTOMER_ID
\set item_count :DEBUG_ITEM_COUNT
\else
\set customer_slot random(0, ((:NUM_CUSTOMERS - :merchant_id) / :NUM_MERCHANTS))
\set customer_id :merchant_id + (:customer_slot * :NUM_MERCHANTS)
\set item_count random(:MIN_ITEMS_PER_ORDER, :MAX_ITEMS_PER_ORDER)
\endif

\set order_ok 1
\set order_total 0.0

BEGIN;

-- retrieve customer information
SELECT CASE WHEN EXISTS (
  SELECT customer_name, email
  FROM customers
  WHERE merchant_id = (:merchant_id)::bigint
    AND customer_id = (:customer_id)::bigint
) THEN 1 ELSE 0 END AS customer_ok
\gset t1_

\if :t1_customer_ok
SELECT nextval('benchmark_order_id_seq') AS new_order_id
\gset
\else
\set order_ok 0
\set new_order_id 0
\endif

-- insert new order
\if :order_ok
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
\endif

\if :order_ok
\if :item_count >= 1

\if :DEBUG_MODE
\set product_id_1 :DEBUG_PRODUCT_ID_1
\set qty_1 :DEBUG_QTY_1
\else
\set product_slot_1 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_1 :merchant_id + (:product_slot_1 * :NUM_MERCHANTS)
\set qty_1 random(:MIN_ORDER_QTY, :MAX_ORDER_QTY)
\endif

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

\if :item1_product_ok
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
            THEN 1 ELSE 0 END AS stock_ok
\gset item1_

\if :item1_stock_ok
SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset item1_

-- insert into order_items for item 1
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

\set order_total :order_total + (:qty_1 * :item1_price)
\else
\set order_ok 0
\endif
-- \endif for \if :item1_stock_ok
\else
\set order_ok 0
\endif
-- \endif for \if :item1_product_ok

\endif
-- \endif for \if :item_count >= 1
\endif
-- \endif for \if :order_ok


\if :order_ok
\if :item_count >= 2

\if :DEBUG_MODE
\set product_id_2 :DEBUG_PRODUCT_ID_2
\set qty_2 :DEBUG_QTY_2
\else
\set product_slot_2 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_2 :merchant_id + (:product_slot_2 * :NUM_MERCHANTS)
\set qty_2 random(:MIN_ORDER_QTY, :MAX_ORDER_QTY)
\endif

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

\if :item2_product_ok
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
            THEN 1 ELSE 0 END AS stock_ok
\gset item2_

\if :item2_stock_ok
SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset item2_

-- insert into order_items for item 2
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

\set order_total :order_total + (:qty_2 * :item2_price)
\else
\set order_ok 0
\endif
-- \endif for \if :item2_stock_ok
\else
\set order_ok 0
\endif
-- \endif for \if :item2_product_ok

\endif
-- \endif for \if :item_count >= 2
\endif
-- \endif for \if :order_ok

\if :order_ok
\if :item_count >= 3

\if :DEBUG_MODE
\set product_id_3 :DEBUG_PRODUCT_ID_3
\set qty_3 :DEBUG_QTY_3
\else
\set product_slot_3 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_3 :merchant_id + (:product_slot_3 * :NUM_MERCHANTS)
\set qty_3 random(:MIN_ORDER_QTY, :MAX_ORDER_QTY)
\endif

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

\if :item3_product_ok
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
            THEN 1 ELSE 0 END AS stock_ok
\gset item3_

\if :item3_stock_ok
SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset item3_

-- insert into order_items for item 3
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

\set order_total :order_total + (:qty_3 * :item3_price)
\else
\set order_ok 0
\endif
-- \endif for \if :item3_stock_ok
\else
\set order_ok 0
\endif
-- \endif for \if :item3_product_ok

\endif
-- \endif for \if :item_count >= 3
\endif
-- \endif for \if :order_ok

\if :order_ok
\if :item_count >= 4

\if :DEBUG_MODE
\set product_id_4 :DEBUG_PRODUCT_ID_4
\set qty_4 :DEBUG_QTY_4
\else
\set product_slot_4 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_4 :merchant_id + (:product_slot_4 * :NUM_MERCHANTS)
\set qty_4 random(:MIN_ORDER_QTY, :MAX_ORDER_QTY)
\endif

SELECT
  CASE WHEN EXISTS (
    SELECT 1
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_4)::bigint
  ) THEN 1 ELSE 0 END AS product_ok,
  COALESCE((
    SELECT price
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_4)::bigint
    LIMIT 1
  ), 0.00)::numeric(12,2) AS price
\gset item4_

\if :item4_product_ok
WITH reserved AS (
  UPDATE inventory
  SET quantity = quantity - (:qty_4)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:product_id_4)::bigint
    AND merchant_id = (:merchant_id)::bigint
    AND product_id = (:product_id_4)::bigint
    AND quantity >= (:qty_4)::integer
  RETURNING 1
)
SELECT CASE WHEN EXISTS (SELECT 1 FROM reserved)
            THEN 1 ELSE 0 END AS stock_ok
\gset item4_

\if :item4_stock_ok
SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset item4_

-- insert into order_items for item 4
INSERT INTO order_items(
  order_item_id, merchant_id, order_id, product_id, quantity, unit_price
)
VALUES(
  (:item4_order_item_id)::bigint,
  (:merchant_id)::bigint,
  (:new_order_id)::bigint,
  (:product_id_4)::bigint,
  (:qty_4)::integer,
  :item4_price
);

\set order_total :order_total + (:qty_4 * :item4_price)
\else
\set order_ok 0
\endif
-- \endif for \if :item4_stock_ok
\else
\set order_ok 0
\endif
-- \endif for \if :item4_product_ok

\endif
-- \endif for \if :item_count >= 4
\endif
-- \endif for \if :order_ok

\if :order_ok
\if :item_count >= 5

\if :DEBUG_MODE
\set product_id_5 :DEBUG_PRODUCT_ID_5
\set qty_5 :DEBUG_QTY_5
\else
\set product_slot_5 random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id_5 :merchant_id + (:product_slot_5 * :NUM_MERCHANTS)
\set qty_5 random(:MIN_ORDER_QTY, :MAX_ORDER_QTY)
\endif

SELECT
  CASE WHEN EXISTS (
    SELECT 1
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_5)::bigint
  ) THEN 1 ELSE 0 END AS product_ok,
  COALESCE((
    SELECT price
    FROM products
    WHERE merchant_id = (:merchant_id)::bigint
      AND product_id = (:product_id_5)::bigint
    LIMIT 1
  ), 0.00)::numeric(12,2) AS price
\gset item5_

\if :item5_product_ok
WITH reserved AS (
  UPDATE inventory
  SET quantity = quantity - (:qty_5)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:product_id_5)::bigint
    AND merchant_id = (:merchant_id)::bigint
    AND product_id = (:product_id_5)::bigint
    AND quantity >= (:qty_5)::integer
  RETURNING 1
)
SELECT CASE WHEN EXISTS (SELECT 1 FROM reserved)
            THEN 1 ELSE 0 END AS stock_ok
\gset item5_

\if :item5_stock_ok
SELECT nextval('benchmark_order_item_id_seq') AS order_item_id
\gset item5_

-- insert into order_items for item 5
INSERT INTO order_items(
  order_item_id, merchant_id, order_id, product_id, quantity, unit_price
)
VALUES(
  (:item5_order_item_id)::bigint,
  (:merchant_id)::bigint,
  (:new_order_id)::bigint,
  (:product_id_5)::bigint,
  (:qty_5)::integer,
  :item5_price
);

\set order_total :order_total + (:qty_5 * :item5_price)
\else
\set order_ok 0
\endif
-- \endif for \if :item5_stock_ok
\else
\set order_ok 0
\endif
-- \endif for \if :item5_product_ok

\endif
-- \endif for \if :item_count >= 5
\endif
-- \endif for \if :order_ok

-- update total_amount for orders
\if :order_ok
UPDATE orders
SET total_amount = (:order_total)::numeric(12,2)
WHERE order_id = (:new_order_id)::bigint;
COMMIT;
\else
ROLLBACK;
\endif

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



-- Sequence values are allocated on the coordinator. Gaps on an unsuccessful
-- order are harmless. The function call writes all order rows atomically.
SELECT nextval('benchmark_order_id_seq') AS order_id,
       nextval('benchmark_order_item_id_seq') AS item_id_1,
       nextval('benchmark_order_item_id_seq') AS item_id_2,
       nextval('benchmark_order_item_id_seq') AS item_id_3,
       nextval('benchmark_order_item_id_seq') AS item_id_4,
       nextval('benchmark_order_item_id_seq') AS item_id_5
\gset t1_

SELECT public.a8_place_order(
  (:merchant_id)::bigint,
  (:customer_id)::bigint,
  (:item_count)::integer,
  ARRAY[(:product_id_1)::bigint, (:product_id_2)::bigint,
        (:product_id_3)::bigint, (:product_id_4)::bigint,
        (:product_id_5)::bigint],
  ARRAY[(:qty_1)::integer, (:qty_2)::integer, (:qty_3)::integer,
        (:qty_4)::integer, (:qty_5)::integer],
  (:t1_order_id)::bigint,
  ARRAY[(:t1_item_id_1)::bigint, (:t1_item_id_2)::bigint,
        (:t1_item_id_3)::bigint, (:t1_item_id_4)::bigint,
        (:t1_item_id_5)::bigint]
) AS created
\gset t1_

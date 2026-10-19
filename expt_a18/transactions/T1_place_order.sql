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


-- No BEGIN/COMMIT as each statement below is its own transaction.
SELECT
  nextval('benchmark_order_id_seq') AS order_id,
  CASE WHEN (:item_count)::integer >= 1 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_1,
  CASE WHEN (:item_count)::integer >= 2 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_2,
  CASE WHEN (:item_count)::integer >= 3 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_3,
  CASE WHEN (:item_count)::integer >= 4 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_4,
  CASE WHEN (:item_count)::integer >= 5 THEN nextval('benchmark_order_item_id_seq') ELSE 0 END AS item_id_5
\gset t1_

-- The rest of T1 is one call to the distributed function defined at the end
-- of this file.
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

-- place_order: the function is distributed by p_merchant_id and colocated 
--with merchants, so SELECT public.place_order() is delegated whole to the
-- worker that holds that merchant's shards, and runs as one transaction.
\if 0
CREATE OR REPLACE FUNCTION public.place_order(
  p_merchant_id bigint,
  p_customer_id bigint,
  p_order_id    bigint,
  p_item_count  integer,
  p_product_ids bigint[],   -- five slots
  p_quantities  integer[],
  p_item_ids    bigint[]
)
RETURNS boolean             -- true when the order was placed
LANGUAGE plpgsql
AS $fn$
DECLARE
  r              record;
  k              integer;
  v_stock        integer;
  v_price        numeric(12,2);
  v_rows         integer;
  v_prod_ids     bigint[]  := '{}';   -- distinct products, in product_id order
  v_prod_qtys    integer[] := '{}';   -- combined quantity per product
  v_prod_prices  numeric[] := '{}';   -- price per product
  v_total        numeric   := 0;
  v_order_total  numeric(12,2);
  v_created_at   timestamp;
BEGIN
  -- 1. The customer must belong to the merchant.
  PERFORM 1
  FROM public.customers c
  WHERE c.merchant_id = p_merchant_id
    AND c.customer_id = p_customer_id;
  IF NOT FOUND THEN
    RETURN false;
  END IF;

  -- 2. Every requested product must exist and have stock for its combined
  --    quantity, since one product can fill several slots.
  FOR r IN
    SELECT ri.product_id, SUM(ri.quantity)::integer AS quantity
    FROM unnest(p_product_ids[1:p_item_count], p_quantities[1:p_item_count])
           AS ri(product_id, quantity)
    GROUP BY ri.product_id
    ORDER BY ri.product_id
  LOOP
    SELECT i.quantity, p.price
    INTO v_stock, v_price
    FROM public.inventory i
    JOIN public.products p
      ON p.merchant_id = p_merchant_id
     AND p.product_id = i.product_id
    WHERE i.merchant_id = p_merchant_id
      AND i.product_id = r.product_id;
    IF NOT FOUND OR v_stock < r.quantity THEN
      RETURN false;
    END IF;

    v_prod_ids    := v_prod_ids || r.product_id;
    v_prod_qtys   := v_prod_qtys || r.quantity;
    v_prod_prices := v_prod_prices || v_price;
    v_total       := v_total + r.quantity * v_price;
  END LOOP;

  -- 3. Reserve the stock, one row per product in product_id order, so
  --    concurrent orders for the same merchant take row locks in one order.
  FOR k IN 1 .. coalesce(array_length(v_prod_ids, 1), 0) LOOP
    UPDATE public.inventory i
    SET quantity   = i.quantity - v_prod_qtys[k],
        updated_at = CURRENT_TIMESTAMP
    WHERE i.merchant_id = p_merchant_id
      AND i.product_id = v_prod_ids[k];
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    IF v_rows <> 1 THEN
      -- Unreachable: step 2 found the row and nothing deletes inventory.
      -- Raising rolls back the reservations made so far.
      RAISE EXCEPTION 'place_order: inventory row for product % not found',
        v_prod_ids[k];
    END IF;
  END LOOP;

  -- 4. The order.
  INSERT INTO public.orders (
    order_id, merchant_id, customer_id, order_status, total_amount, created_at
  )
  VALUES (
    p_order_id, p_merchant_id, p_customer_id, 'PENDING',
    v_total::numeric(12,2), CURRENT_TIMESTAMP
  )
  RETURNING total_amount, created_at INTO v_order_total, v_created_at;

  -- 5. The items, in slot order, each at its product's current price.
  FOR k IN 1 .. p_item_count LOOP
    v_price := v_prod_prices[array_position(v_prod_ids, p_product_ids[k])];

    INSERT INTO public.order_items (
      order_item_id, merchant_id, order_id, product_id, quantity, unit_price
    )
    VALUES (
      p_item_ids[k], p_merchant_id, p_order_id, p_product_ids[k],
      p_quantities[k], v_price
    );
  END LOOP;

  -- 6. Keep the T6 rollup in step, in this order's slot of the merchant-day.
  INSERT INTO public.merchant_daily_sales AS s (
    merchant_id, sales_date, slot, order_count, revenue
  )
  VALUES (p_merchant_id, v_created_at::date, (p_order_id % 4)::smallint, 1, v_order_total)
  ON CONFLICT (merchant_id, sales_date, slot)
  DO UPDATE SET order_count = s.order_count + 1,
                revenue     = s.revenue + EXCLUDED.revenue;

  -- 7. order_merchant_map is sharded by order_id, so this row usually lives
  --    on another worker. This worker then coordinates the two-phase commit
  --    itself, and the order still commits or rolls back as one.
  INSERT INTO public.order_merchant_map (order_id, merchant_id)
  VALUES (p_order_id, p_merchant_id);

  RETURN true;
END;
$fn$;

SELECT create_distributed_function(
  'public.place_order(bigint, bigint, bigint, integer, bigint[], integer[], bigint[])',
  'p_merchant_id',
  colocate_with => 'merchants'
);

-- Delegation needs metadata on the target worker. Recorded in schema-create.log.
SELECT nodename, nodeport, hasmetadata, metadatasynced
FROM pg_dist_node
ORDER BY nodename;
\endif

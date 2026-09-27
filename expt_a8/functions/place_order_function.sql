-- T1's merchant-local work is delegated to the worker holding this merchant's shards.
-- IDs are allocated by the coordinator and passed in by the caller.
CREATE OR REPLACE FUNCTION public.a8_place_order(
  p_merchant_id bigint,
  p_customer_id bigint,
  p_item_count integer,
  p_product_ids bigint[],
  p_quantities integer[],
  p_order_id bigint,
  p_item_ids bigint[]
) RETURNS boolean
LANGUAGE plpgsql
VOLATILE
AS $function$
DECLARE
  v_requirement record;
  v_available integer;
  v_price numeric(12,2);
  v_prices numeric[] := ARRAY[]::numeric[];
  v_total numeric := 0;
  v_i integer;
  v_updated integer;
BEGIN
  IF p_item_count NOT BETWEEN 1 AND 5
     OR cardinality(p_product_ids) <> 5
     OR cardinality(p_quantities) <> 5
     OR cardinality(p_item_ids) <> 5 THEN
    RAISE EXCEPTION 'invalid T1 item arrays or item count';
  END IF;

  PERFORM 1
  FROM public.customers
  WHERE merchant_id = p_merchant_id AND customer_id = p_customer_id;
  IF NOT FOUND THEN
    RETURN false;
  END IF;

  -- Lock in product-id order, including duplicates only once. No stock is
  -- changed until every requested product and its total quantity pass.
  FOR v_requirement IN
    SELECT product_id, SUM(quantity)::integer AS needed
    FROM unnest(p_product_ids[1:p_item_count],
                p_quantities[1:p_item_count]) AS item(product_id, quantity)
    GROUP BY product_id
    ORDER BY product_id
  LOOP
    IF v_requirement.product_id IS NULL OR v_requirement.needed IS NULL
       OR v_requirement.needed <= 0 THEN
      RETURN false;
    END IF;

    SELECT i.quantity INTO v_available
    FROM public.inventory AS i
    WHERE i.merchant_id = p_merchant_id
      AND i.product_id = v_requirement.product_id
    FOR UPDATE;
    IF NOT FOUND OR v_available < v_requirement.needed THEN
      RETURN false;
    END IF;
  END LOOP;

  -- Retain one unit price per input slot, including duplicate selections.
  FOR v_i IN 1..p_item_count LOOP
    IF p_quantities[v_i] IS NULL OR p_quantities[v_i] <= 0 THEN
      RETURN false;
    END IF;

    SELECT p.price INTO v_price
    FROM public.products AS p
    WHERE p.merchant_id = p_merchant_id
      AND p.product_id = p_product_ids[v_i];
    IF NOT FOUND THEN
      RETURN false;
    END IF;

    v_prices := array_append(v_prices, v_price);
    v_total := v_total + p_quantities[v_i] * v_price;
  END LOOP;

  FOR v_requirement IN
    SELECT product_id, SUM(quantity)::integer AS needed
    FROM unnest(p_product_ids[1:p_item_count],
                p_quantities[1:p_item_count]) AS item(product_id, quantity)
    GROUP BY product_id
    ORDER BY product_id
  LOOP
    UPDATE public.inventory
    SET quantity = quantity - v_requirement.needed,
        updated_at = CURRENT_TIMESTAMP
    WHERE merchant_id = p_merchant_id
      AND product_id = v_requirement.product_id
      AND quantity >= v_requirement.needed;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
      RAISE EXCEPTION 'T1 stock changed after validation for product %',
        v_requirement.product_id USING ERRCODE = '40001';
    END IF;
  END LOOP;

  INSERT INTO public.orders (
    order_id, merchant_id, customer_id, order_status, total_amount, created_at
  ) VALUES (
    p_order_id, p_merchant_id, p_customer_id, 'PENDING', v_total, CURRENT_TIMESTAMP
  );

  FOR v_i IN 1..p_item_count LOOP
    INSERT INTO public.order_items (
      order_item_id, merchant_id, order_id, product_id, quantity, unit_price
    ) VALUES (
      p_item_ids[v_i], p_merchant_id, p_order_id,
      p_product_ids[v_i], p_quantities[v_i], v_prices[v_i]
    );
  END LOOP;

  -- This table is distributed by order_id and may live on another worker.
  -- Its insert is part of the same distributed function call.
  INSERT INTO public.order_route (order_id, merchant_id)
  VALUES (p_order_id, p_merchant_id);

  RETURN true;
END;
$function$;

SELECT create_distributed_function(
  'public.a8_place_order(bigint,bigint,integer,bigint[],integer[],bigint,bigint[])',
  'p_merchant_id',
  colocate_with => 'orders',
  force_delegation => true
);

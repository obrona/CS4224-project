-- Run on the coordinator after the merchant-colocated tables are distributed.
-- IDs are allocated by the coordinator because its benchmark sequences are global.
CREATE OR REPLACE FUNCTION public.place_order_on_merchant(
  p_merchant_id bigint,
  p_customer_id bigint,
  p_item_count integer,
  p_product_ids bigint[],
  p_quantities integer[],
  p_order_id bigint,
  p_order_item_ids bigint[]
) RETURNS bigint
LANGUAGE plpgsql
AS $function$
DECLARE
  v_order_id bigint;
BEGIN
  WITH
  input_items(item_no, product_id, quantity) AS (
    VALUES
      (1, p_product_ids[1], p_quantities[1]),
      (2, p_product_ids[2], p_quantities[2]),
      (3, p_product_ids[3], p_quantities[3]),
      (4, p_product_ids[4], p_quantities[4]),
      (5, p_product_ids[5], p_quantities[5])
  ),
  requested_items AS MATERIALIZED (
    SELECT item_no, product_id, quantity
    FROM input_items
    WHERE item_no <= p_item_count
  ),
  requirements AS MATERIALIZED (
    SELECT product_id, SUM(quantity)::integer AS quantity
    FROM requested_items
    GROUP BY product_id
  ),
  eligible AS MATERIALIZED (
    SELECT
      EXISTS (
        SELECT 1 FROM public.customers c
        WHERE c.merchant_id = p_merchant_id
          AND c.customer_id = p_customer_id
      )
      AND NOT EXISTS (
        SELECT 1
        FROM requirements r
        LEFT JOIN public.products p
          ON p.merchant_id = p_merchant_id
         AND p.product_id = r.product_id
        LEFT JOIN public.inventory i
          ON i.merchant_id = p_merchant_id
         AND i.product_id = r.product_id
        WHERE p.product_id IS NULL
           OR i.product_id IS NULL
           OR i.quantity < r.quantity
      ) AS ok
  ),
  reserved AS (
    UPDATE public.inventory i
    SET quantity = i.quantity - r.quantity,
        updated_at = CURRENT_TIMESTAMP
    FROM requirements r, eligible e
    WHERE e.ok
      AND i.merchant_id = p_merchant_id
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
    INSERT INTO public.orders (
      order_id, merchant_id, customer_id, order_status, total_amount, created_at
    )
    SELECT
      p_order_id,
      p_merchant_id,
      p_customer_id,
      'PENDING'::text,
      SUM(ri.quantity * p.price)::numeric(12,2),
      CURRENT_TIMESTAMP
    FROM requested_items ri
    JOIN public.products p
      ON p.merchant_id = p_merchant_id
     AND p.product_id = ri.product_id
    CROSS JOIN reservation_ok ro
    WHERE ro.ok
    HAVING COUNT(*) = p_item_count
    RETURNING order_id
  ),
  inserted_items AS (
    INSERT INTO public.order_items (
      order_item_id, merchant_id, order_id, product_id, quantity, unit_price
    )
    SELECT
      p_order_item_ids[ri.item_no],
      p_merchant_id,
      o.order_id,
      ri.product_id,
      ri.quantity,
      p.price
    FROM requested_items ri
    JOIN public.products p
      ON p.merchant_id = p_merchant_id
     AND p.product_id = ri.product_id
    CROSS JOIN inserted_order o
    RETURNING 1
  )
  SELECT o.order_id INTO v_order_id
  FROM inserted_order o;

  -- Zero means validation or stock reservation prevented the order.
  RETURN COALESCE(v_order_id, 0);
END;
$function$;

-- Route by p_merchant_id to the merchants shard; all T1 tables share its placement.
SELECT create_distributed_function(
  'public.place_order_on_merchant(bigint,bigint,integer,bigint[],integer[],bigint,bigint[])',
  'p_merchant_id',
  colocate_with => 'public.merchants'
);

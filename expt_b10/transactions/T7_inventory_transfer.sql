\if :DEBUG_MODE
\set source_product_id :DEBUG_T7_SOURCE_PRODUCT_ID
\set dest_product_id :DEBUG_T7_DEST_PRODUCT_ID
\set transfer_qty :DEBUG_T7_TRANSFER_QTY
\else
\set source_product_id random(1, :NUM_PRODUCTS)
\set dest_product_id random(1, :NUM_PRODUCTS)
\set transfer_qty random(:T7_MIN_TRANSFER_QTY, :T7_MAX_TRANSFER_QTY)
\endif

\set transfer_ok 1

-- T7 is given product id, but inventory is sharded by merchant_id.
-- product_merchant_map is sharded by product_id, so each lookup is routed to a
-- single shard.
SELECT COALESCE(MAX(merchant_id), 0) AS source_merchant_id
FROM product_merchant_map
WHERE product_id = (:source_product_id)::bigint
\gset t7_

SELECT COALESCE(MAX(merchant_id), 0) AS dest_merchant_id
FROM product_merchant_map
WHERE product_id = (:dest_product_id)::bigint
\gset t7_

\if :source_product_id = :dest_product_id
\set transfer_ok 0
\endif

\if :t7_source_merchant_id = 0 OR :t7_dest_merchant_id = 0
-- Fallback when a product is missing from the map.
BEGIN;

SELECT EXISTS(
  SELECT 1 FROM inventory
  WHERE product_id = (:source_product_id)::bigint
) AS source_exists
\gset t7_

SELECT EXISTS(
  SELECT 1 FROM inventory
  WHERE product_id = (:dest_product_id)::bigint
) AS dest_exists
\gset t7_

\if :t7_source_exists
SELECT inventory_id AS source_inventory_id FROM inventory WHERE product_id = (:source_product_id)::bigint
\gset
\else
\set transfer_ok 0
\endif

\if :t7_dest_exists
SELECT inventory_id AS dest_inventory_id FROM inventory WHERE product_id = (:dest_product_id)::bigint
\gset
\else
\set transfer_ok 0
\endif

\if :transfer_ok
WITH debit AS (
  UPDATE inventory
  SET quantity = quantity - (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:source_inventory_id)::bigint
    AND quantity >= (:transfer_qty)::integer
  RETURNING 1
)
SELECT EXISTS(SELECT 1 FROM debit) AS debit_ok
\gset t7_

\if :t7_debit_ok
WITH credit AS (
  UPDATE inventory
  SET quantity = quantity + (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE inventory_id = (:dest_inventory_id)::bigint
  RETURNING 1
)
SELECT EXISTS(SELECT 1 FROM credit) AS credit_ok
\gset t7_

\if :t7_credit_ok
\else
\set transfer_ok 0
\endif
\else
\set transfer_ok 0
\endif
\endif

\if :transfer_ok
COMMIT;
\else
ROLLBACK;
\endif

\elif :transfer_ok
-- The transfer is one call to the distributed function transfer_inventory.
SELECT public.transfer_inventory(
  (:t7_source_merchant_id)::bigint,
  (:source_product_id)::bigint,
  (:t7_dest_merchant_id)::bigint,
  (:dest_product_id)::bigint,
  (:transfer_qty)::integer
);
\endif

-- transfer_inventory:
-- The function is distributed by p_src_merchant_id and colocated with
-- merchants. A top-level call is delegated to the worker that holds the
-- source merchant's shard, and the debit runs on that local shard. The credit
-- is local when the destination merchant's shard is on the same worker.
-- Otherwise the worker sends it to the destination's worker and coordinates
-- the two-phase commit itself.
\if 0
CREATE OR REPLACE FUNCTION public.transfer_inventory(
  p_src_merchant_id bigint,
  p_src_product_id  bigint,
  p_dst_merchant_id bigint,
  p_dst_product_id  bigint,
  p_qty             integer
)
RETURNS boolean             -- true when the transfer was made
LANGUAGE plpgsql
AS $fn$
DECLARE
  v_rows integer;
BEGIN
  -- Debit, guarded so stock will never go negative.
  UPDATE public.inventory
  SET quantity   = quantity - p_qty,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = p_src_merchant_id
    AND product_id = p_src_product_id
    AND quantity >= p_qty;
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  IF v_rows = 0 THEN
    RETURN false;
  END IF;

  -- Credit.
  UPDATE public.inventory
  SET quantity   = quantity + p_qty,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = p_dst_merchant_id
    AND product_id = p_dst_product_id;
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  IF v_rows <> 1 THEN
    RAISE EXCEPTION 'transfer_inventory: no inventory row for product %',
      p_dst_product_id;
  END IF;

  RETURN true;
END;
$fn$;

SELECT create_distributed_function(
  'public.transfer_inventory(bigint, bigint, bigint, bigint, integer)',
  'p_src_merchant_id',
  colocate_with => 'merchants'
);
\endif

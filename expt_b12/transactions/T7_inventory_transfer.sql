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
-- product_merchant_map is sharded by product_id. Both merchant ids are read in
-- one statement, so this is one round trip instead of two.
SELECT COALESCE(MAX(merchant_id) FILTER (WHERE product_id = (:source_product_id)::bigint), 0) AS source_merchant_id,
       COALESCE(MAX(merchant_id) FILTER (WHERE product_id = (:dest_product_id)::bigint), 0) AS dest_merchant_id
FROM product_merchant_map
WHERE product_id IN ((:source_product_id)::bigint, (:dest_product_id)::bigint)
\gset t7_

\if :source_product_id = :dest_product_id
\set transfer_ok 0
\endif

BEGIN;

\if :t7_source_merchant_id = 0 OR :t7_dest_merchant_id = 0
-- Fallback when a product is missing from the map.
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

\else
-- Routed path where each UPDATE names its row's merchant_id, so it goes to one
-- shard and uses the UNIQUE (merchant_id, product_id) index.
\if :transfer_ok
WITH debit AS (
  UPDATE inventory
  SET quantity = quantity - (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = (:t7_source_merchant_id)::bigint
    AND product_id = (:source_product_id)::bigint
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
  WHERE merchant_id = (:t7_dest_merchant_id)::bigint
    AND product_id = (:dest_product_id)::bigint
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
\endif

\if :transfer_ok
COMMIT;
\else
ROLLBACK;
\endif

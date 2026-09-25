\if :DEBUG_MODE
\set source_product_id :DEBUG_T7_SOURCE_PRODUCT_ID
\set dest_product_id :DEBUG_T7_DEST_PRODUCT_ID
\else
\set source_product_id random(1, :NUM_PRODUCTS)
\set dest_product_id random(1, :NUM_PRODUCTS)
\endif

-- A transfer to the same product does no work.
\if :source_product_id = :dest_product_id
\else
\if :DEBUG_MODE
\set transfer_qty :DEBUG_T7_TRANSFER_QTY
\else
\set transfer_qty random(:T7_MIN_TRANSFER_QTY, :T7_MAX_TRANSFER_QTY)
\endif

\set transfer_ok 1
BEGIN;

-- Each lookup targets one locator shard. Aggregates always return a row,
-- including when a product is absent.
SELECT COUNT(*) AS found,
       MAX(merchant_id) AS merchant_id,
       MAX(inventory_id) AS inventory_id
FROM inventory_locator
WHERE product_id = (:source_product_id)::bigint
\gset t7_source_

SELECT COUNT(*) AS found,
       MAX(merchant_id) AS merchant_id,
       MAX(inventory_id) AS inventory_id
FROM inventory_locator
WHERE product_id = (:dest_product_id)::bigint
\gset t7_dest_

\if :t7_source_found
\else
\set transfer_ok 0
\endif
\if :t7_dest_found
\else
\set transfer_ok 0
\endif
\if :transfer_ok
WITH debit AS (
  UPDATE inventory
  SET quantity = quantity - (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE merchant_id = (:t7_source_merchant_id)::bigint
    AND inventory_id = (:t7_source_inventory_id)::bigint
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
    AND inventory_id = (:t7_dest_inventory_id)::bigint
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

\if :transfer_ok
COMMIT;
\else
ROLLBACK;
\endif
\endif

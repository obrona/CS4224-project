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

\if :source_product_id = :dest_product_id
\set transfer_ok 0
\endif

BEGIN;

-- In this layout inventory is placed by product (see optimisations.md), so
-- each UPDATE is routed by product_id alone and T7 needs no lookup table. A
-- product has one inventory row; UNIQUE (product_id, merchant_id) leads with
-- product_id, so each UPDATE is one index probe.
\if :transfer_ok
WITH debit AS (
  UPDATE inventory
  SET quantity = quantity - (:transfer_qty)::integer,
      updated_at = CURRENT_TIMESTAMP
  WHERE product_id = (:source_product_id)::bigint
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
  WHERE product_id = (:dest_product_id)::bigint
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

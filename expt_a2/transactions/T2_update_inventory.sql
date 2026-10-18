\if :DEBUG_MODE
\set merchant_id :DEBUG_MERCHANT_ID
\else
\set merchant_id CASE WHEN random(1, 100) <= :HOT_ORDER_PERCENT THEN random(1, :HOT_MERCHANTS) ELSE random((:HOT_MERCHANTS + 1), :NUM_MERCHANTS) END
\endif

\if :DEBUG_MODE
\set product_id :DEBUG_PRODUCT_ID
\set inventory_change :DEBUG_INVENTORY_CHANGE
\else
\set product_slot random(0, ((:NUM_PRODUCTS - :merchant_id) / :NUM_MERCHANTS))
\set product_id :merchant_id + (:product_slot * :NUM_MERCHANTS)
\set inventory_change random(:INVENTORY_CHANGE_MIN, :INVENTORY_CHANGE_MAX)
\endif

BEGIN;

UPDATE inventory
SET quantity = quantity + (:inventory_change)::integer,
    updated_at = CURRENT_TIMESTAMP
WHERE inventory_id = (:product_id)::bigint
  AND merchant_id = (:merchant_id)::bigint
  AND product_id = (:product_id)::bigint
  AND quantity + (:inventory_change)::integer >= 0;

COMMIT;

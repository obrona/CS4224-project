\if :DEBUG_MODE
\set order_id :DEBUG_ORDER_ID
\set status_roll :DEBUG_STATUS_ROLL
\else
\set order_id random(1, :INITIAL_NUM_ORDERS)
\set status_roll random(1, 3)
\endif
SELECT CASE
  WHEN h1 % 10000 < (:HOT_ORDER_PERCENT)::bigint * 100
    THEN 1 + h2 % (:HOT_MERCHANTS)::bigint
  ELSE (:HOT_MERCHANTS)::bigint + 1
       + h2 % ((:NUM_MERCHANTS)::bigint - (:HOT_MERCHANTS)::bigint)
END::bigint AS merchant_id
FROM (
  SELECT
    hashint8extended((:order_id)::bigint, (:DATA_SEED)::bigint)
      & 9223372036854775807::bigint AS h1,
    hashint8extended((:order_id)::bigint, (:DATA_SEED)::bigint + 1)
      & 9223372036854775807::bigint AS h2
) AS hashes
\gset t5_



\if :status_roll = 1
UPDATE orders
SET order_status = 'PENDING'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'PENDING'::text;
\elif :status_roll = 2
UPDATE orders
SET order_status = 'SHIPPED'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'SHIPPED'::text;
\else
UPDATE orders
SET order_status = 'COMPLETED'::text
WHERE merchant_id = (:t5_merchant_id)::bigint
  AND order_id = (:order_id)::bigint
  AND order_status IS DISTINCT FROM 'COMPLETED'::text;
\endif


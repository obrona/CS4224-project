
EXPLAIN (VERBOSE)
INSERT INTO order_merchant_map (order_id, merchant_id)
VALUES ((:new_order_id)::bigint, (:merchant_id)::bigint);

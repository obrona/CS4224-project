
EXPLAIN (VERBOSE)
INSERT INTO merchant_daily_sales AS s (merchant_id, sales_date, order_count, revenue)
VALUES ((:merchant_id)::bigint, CURRENT_TIMESTAMP::date, 1, (1.00)::numeric(12,2))
ON CONFLICT (merchant_id, sales_date)
DO UPDATE SET order_count = s.order_count + 1,
              revenue     = s.revenue + EXCLUDED.revenue;

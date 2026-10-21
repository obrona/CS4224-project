-- Same window as the baseline using a per-merchant/day rollup for
-- whole days, combined with a live scan of orders for the boundary day.
WITH partial_day AS (
  SELECT
    o.merchant_id,
    COUNT(*) AS order_count,
    SUM(o.total_amount) AS revenue
  FROM orders AS o
  WHERE o.created_at >= CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day'
    AND o.created_at < CURRENT_TIMESTAMP
    AND o.created_at < (CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day')::date + 1
  GROUP BY o.merchant_id
),
whole_days AS (
  SELECT
    s.merchant_id,
    SUM(s.order_count) AS order_count,
    SUM(s.revenue) AS revenue
  FROM merchant_daily_sales AS s
  WHERE s.sales_date >= (CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day')::date + 1
  GROUP BY s.merchant_id
)
SELECT
  merchant_id,
  SUM(order_count) AS order_count,
  SUM(revenue) AS revenue
FROM (
  SELECT merchant_id, order_count, revenue FROM partial_day
  UNION ALL
  SELECT merchant_id, order_count, revenue FROM whole_days
) AS combined
GROUP BY merchant_id
ORDER BY revenue DESC
LIMIT 20;

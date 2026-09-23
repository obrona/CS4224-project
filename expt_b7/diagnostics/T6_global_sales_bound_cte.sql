-- T6 as run in expt_b6 (job-875073). Kept for EXPLAIN comparison only.
WITH bound AS (
  SELECT
    CURRENT_TIMESTAMP AS now_ts,
    CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day' AS win_start
),
partial_day AS (
  SELECT
    o.merchant_id,
    COUNT(*) AS order_count,
    SUM(o.total_amount) AS revenue
  FROM orders AS o
  CROSS JOIN bound AS b
  WHERE o.created_at >= b.win_start
    AND o.created_at < b.now_ts
    AND o.created_at < ((b.win_start)::date + 1)
  GROUP BY o.merchant_id
),
whole_days AS (
  SELECT
    s.merchant_id,
    SUM(s.order_count) AS order_count,
    SUM(s.revenue) AS revenue
  FROM merchant_daily_sales AS s
  CROSS JOIN bound AS b
  WHERE s.sales_date >= ((b.win_start)::date + 1)
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

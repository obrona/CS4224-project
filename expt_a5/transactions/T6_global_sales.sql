BEGIN;

SELECT
  merchant_id,
  COUNT(*) AS order_count,
  SUM(total_amount) AS revenue
FROM orders
WHERE created_at >= CURRENT_TIMESTAMP - (:REPORT_DAYS)::integer * INTERVAL '1 day'
  AND created_at < CURRENT_TIMESTAMP
GROUP BY merchant_id
ORDER BY revenue DESC
LIMIT 20;

COMMIT;

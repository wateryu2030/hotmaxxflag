-- 核心指标-平均毛利率（数字卡片）
-- 参数: start_date, end_date
SELECT
  CASE
    WHEN SUM(total_sale) > 0 THEN ROUND(SUM(total_profit) / SUM(total_sale) * 100, 2)
    ELSE 0
  END AS avg_profit_rate_pct
FROM t_htma_profit
WHERE store_id = '沈阳超级仓'
  AND data_date BETWEEN ${start_date} AND ${end_date};

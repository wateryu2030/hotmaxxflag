-- 核心指标-总毛利（数字卡片）
-- 参数: start_date, end_date
SELECT
  COALESCE(SUM(total_profit), 0) AS total_gross_profit
FROM t_htma_profit
WHERE store_id = '沈阳超级仓'
  AND data_date BETWEEN ${start_date} AND ${end_date};

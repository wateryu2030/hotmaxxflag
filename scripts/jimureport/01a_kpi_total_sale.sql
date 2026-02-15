-- 核心指标-总销售额（数字卡片）
-- 参数: start_date, end_date
SELECT
  COALESCE(SUM(total_sale), 0) AS total_sale_amount
FROM t_htma_profit
WHERE store_id = '沈阳超级仓'
  AND data_date BETWEEN ${start_date} AND ${end_date};

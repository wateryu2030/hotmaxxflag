-- 核心指标-库存总额（数字卡片）
-- 说明: 取最新日期的库存汇总，无需日期参数
SELECT
  COALESCE(SUM(stock_amount), 0) AS total_stock_amount
FROM t_htma_stock
WHERE store_id = '沈阳超级仓'
  AND data_date = (
    SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = '沈阳超级仓'
  );

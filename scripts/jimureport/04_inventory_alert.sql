-- =====================================================
-- JimuReport 数据集 - 库存预警
-- 用途: 低库存预警卡片、库存-销售明细表
-- 参数: min_stock_threshold (可选，默认50)
-- =====================================================

-- 1. 库存预警汇总（预警卡片）
SELECT
  COUNT(DISTINCT sku_code) AS alert_sku_count,
  COUNT(DISTINCT category) AS alert_category_count,
  SUM(stock_qty) AS total_alert_stock
FROM t_htma_stock
WHERE store_id = '沈阳超级仓'
  AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = '沈阳超级仓')
  AND stock_qty < IFNULL(${min_stock_threshold}, 50)
  AND stock_qty >= 0;

-- 2. 库存-销售明细表（支持筛选、排序）
SELECT
  s.data_date,
  s.sku_code,
  COALESCE(s.category, st.category, '未分类') AS category,
  COALESCE(st.stock_qty, 0) AS stock_qty,
  s.sale_qty,
  s.sale_amount,
  s.gross_profit,
  CASE
    WHEN COALESCE(st.stock_qty, 0) < IFNULL(${min_stock_threshold}, 50)
    THEN '低库存'
    ELSE '正常'
  END AS stock_status
FROM t_htma_sale s
LEFT JOIN t_htma_stock st
  ON st.sku_code = s.sku_code
  AND st.data_date = s.data_date
  AND st.store_id = s.store_id
WHERE s.store_id = '沈阳超级仓'
  AND s.data_date BETWEEN ${start_date} AND ${end_date}
ORDER BY s.data_date DESC, stock_qty ASC, sale_amount DESC;

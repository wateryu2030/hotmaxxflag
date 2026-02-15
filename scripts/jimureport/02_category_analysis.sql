-- =====================================================
-- JimuReport 数据集 - 品类分析（饼图、柱状图）
-- 用途: 品类销售额占比、品类毛利对比
-- 参数: start_date, end_date
-- =====================================================

-- 1. 品类销售额占比（饼图，Top5 + 其他）
WITH category_sale AS (
  SELECT
    COALESCE(category, '未分类') AS category,
    SUM(sale_amount) AS sale_amount
  FROM t_htma_sale
  WHERE store_id = '沈阳超级仓'
    AND data_date BETWEEN ${start_date} AND ${end_date}
  GROUP BY category
),
ranked AS (
  SELECT
    category,
    sale_amount,
    ROW_NUMBER() OVER (ORDER BY sale_amount DESC) AS rn
  FROM category_sale
)
SELECT
  CASE WHEN rn <= 5 THEN category ELSE '其他' END AS category,
  SUM(sale_amount) AS sale_amount
FROM ranked
GROUP BY CASE WHEN rn <= 5 THEN category ELSE '其他' END
ORDER BY sale_amount DESC;

-- 2. 品类毛利对比（柱状图，按月）
SELECT
  category,
  DATE_FORMAT(data_date, '%Y-%m') AS month_key,
  SUM(gross_profit) AS gross_profit
FROM t_htma_sale
WHERE store_id = '沈阳超级仓'
  AND data_date BETWEEN ${start_date} AND ${end_date}
GROUP BY category, DATE_FORMAT(data_date, '%Y-%m')
ORDER BY month_key, gross_profit DESC;

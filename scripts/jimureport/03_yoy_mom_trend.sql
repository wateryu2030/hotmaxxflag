-- =====================================================
-- JimuReport 数据集 - 同比/环比趋势分析
-- 用途: 销售额环比、毛利率同比
-- 参数: start_date, end_date
-- =====================================================

-- 1. 销售额日环比（组合图：柱状+折线）
WITH daily_sale AS (
  SELECT
    data_date,
    SUM(total_sale) AS daily_amount
  FROM t_htma_profit
  WHERE store_id = '沈阳超级仓'
    AND data_date BETWEEN DATE_SUB(${start_date}, INTERVAL 1 DAY) AND ${end_date}
  GROUP BY data_date
)
SELECT
  t.data_date,
  t.daily_amount,
  prev.daily_amount AS prev_day_amount,
  CASE
    WHEN prev.daily_amount > 0
    THEN ROUND((t.daily_amount - prev.daily_amount) / prev.daily_amount * 100, 2)
    ELSE NULL
  END AS mom_rate_pct
FROM daily_sale t
LEFT JOIN daily_sale prev ON prev.data_date = DATE_SUB(t.data_date, INTERVAL 1 DAY)
WHERE t.data_date BETWEEN ${start_date} AND ${end_date}
ORDER BY t.data_date;

-- 2. 毛利率同比（按周，若有去年同期数据）
WITH weekly_profit AS (
  SELECT
    YEARWEEK(data_date) AS year_week,
    YEAR(data_date) AS year_no,
    SUM(total_sale) AS total_sale,
    SUM(total_profit) AS total_profit,
    CASE WHEN SUM(total_sale) > 0 THEN SUM(total_profit) / SUM(total_sale) * 100 ELSE 0 END AS profit_rate_pct
  FROM t_htma_profit
  WHERE store_id = '沈阳超级仓'
    AND data_date BETWEEN ${start_date} AND ${end_date}
  GROUP BY YEARWEEK(data_date), YEAR(data_date)
),
with_yoy AS (
  SELECT
    year_week,
    year_no,
    profit_rate_pct,
    LAG(profit_rate_pct, 1) OVER (ORDER BY year_week) AS prev_week_rate
  FROM weekly_profit
)
SELECT
  year_week,
  year_no,
  profit_rate_pct,
  prev_week_rate,
  CASE
    WHEN prev_week_rate > 0
    THEN ROUND((profit_rate_pct - prev_week_rate) / prev_week_rate * 100, 2)
    ELSE NULL
  END AS wow_rate_pct
FROM with_yoy
ORDER BY year_week;

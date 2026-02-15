-- 修复总毛利为负：将 sale_amount=0 且 sale_cost>0 的异常行 gross_profit 置为 0
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 htma_dashboard < scripts/fix_negative_gross_profit.sql

USE htma_dashboard;

UPDATE t_htma_sale 
SET gross_profit = 0 
WHERE sale_amount = 0 AND sale_cost > 0;

-- 重新汇总毛利表（含分类层级，需先执行 03_add_full_columns.sql）
TRUNCATE TABLE t_htma_profit;

INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id,
    category_code, category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
SELECT data_date, COALESCE(category, '未分类'),
       SUM(sale_amount), SUM(COALESCE(gross_profit, 0)),
       LEAST(1, GREATEST(0, CASE WHEN SUM(sale_amount) > 0 THEN SUM(COALESCE(gross_profit, 0)) / SUM(sale_amount) ELSE 0 END)),
       store_id,
       MAX(category_code), MAX(category_large_code), MAX(category_large),
       MAX(category_mid_code), MAX(category_mid), MAX(category_small_code), MAX(category_small)
FROM t_htma_sale
GROUP BY data_date, category, store_id;

SELECT 'Done. 已修复异常毛利' AS msg;
SELECT SUM(total_profit) AS total_profit FROM t_htma_profit;

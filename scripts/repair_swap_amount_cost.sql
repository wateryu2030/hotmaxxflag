-- 若导入时金额/进价列错位导致毛利异常为负，可执行此脚本对调 sale_amount 与 sale_cost 并重算毛利
-- 执行前请备份！执行: mysql -h 127.0.0.1 -u root -p62102218 htma_dashboard < scripts/repair_swap_amount_cost.sql

USE htma_dashboard;

-- 对调 sale_amount 与 sale_cost（MySQL 同语句内赋值使用更新前值，故可直接对调）
UPDATE t_htma_sale SET sale_amount = sale_cost, sale_cost = sale_amount;
UPDATE t_htma_sale SET gross_profit = sale_amount - sale_cost;

-- 重新汇总毛利表（含分类层级，需先执行 03_add_full_columns.sql）
TRUNCATE TABLE t_htma_profit;
INSERT INTO t_htma_profit (data_date, category, total_sale, total_profit, profit_rate, store_id,
    category_code, category_large_code, category_large, category_mid_code, category_mid, category_small_code, category_small)
SELECT data_date, COALESCE(category, '未分类'),
       SUM(sale_amount), SUM(COALESCE(gross_profit, 0)),
       LEAST(1, GREATEST(-1, CASE WHEN SUM(sale_amount) > 0 THEN SUM(COALESCE(gross_profit, 0)) / SUM(sale_amount) ELSE 0 END)),
       store_id,
       MAX(category_code), MAX(category_large_code), MAX(category_large),
       MAX(category_mid_code), MAX(category_mid), MAX(category_small_code), MAX(category_small)
FROM t_htma_sale
GROUP BY data_date, category, store_id
ON DUPLICATE KEY UPDATE total_sale=VALUES(total_sale), total_profit=VALUES(total_profit), profit_rate=VALUES(profit_rate),
    category_code=VALUES(category_code), category_large_code=VALUES(category_large_code), category_large=VALUES(category_large),
    category_mid_code=VALUES(category_mid_code), category_mid=VALUES(category_mid),
    category_small_code=VALUES(category_small_code), category_small=VALUES(category_small);

SELECT 'Done. 已对调金额与成本并重算毛利' AS msg;
SELECT SUM(total_sale) AS total_sale, SUM(total_profit) AS total_profit FROM t_htma_profit;

-- =====================================================
-- 好特卖超级仓 - 数据清洗脚本
-- 说明: 在原始数据导入后执行，确保数据质量满足看板需求
-- 执行顺序: 01_create_tables.sql → 导入原始数据 → 本脚本
-- =====================================================

USE htma_dashboard;

-- -----------------------------------------------------
-- 1. 库存表清洗
-- -----------------------------------------------------

-- 1.1 剔除库存数量为负的异常值（可选：改为0或删除）
UPDATE t_htma_stock SET stock_qty = 0 WHERE stock_qty < 0;

-- 或删除异常记录（二选一）：
-- DELETE FROM t_htma_stock WHERE stock_qty < 0;

-- 1.2 补充缺失的品类字段（若存在品类映射表）
UPDATE t_htma_stock s
INNER JOIN t_htma_category_mapping m ON s.sku_code = m.sku_code
SET s.category = m.category
WHERE s.category IS NULL OR s.category = '';

-- 1.3 统一日期格式为 YYYY-MM-DD（若源数据为字符串）
-- 如源字段为 data_date_str，可先新增 date 列再更新：
-- ALTER TABLE t_htma_stock ADD COLUMN data_date DATE;
-- UPDATE t_htma_stock SET data_date = STR_TO_DATE(data_date_str, '%Y-%m-%d');

-- 1.4 统一门店ID
UPDATE t_htma_stock SET store_id = '沈阳超级仓' WHERE store_id IS NULL OR store_id = '';

-- -----------------------------------------------------
-- 2. 销售表清洗
-- -----------------------------------------------------

-- 2.1 计算单品毛利 = 销售额 - 销售成本
UPDATE t_htma_sale
SET gross_profit = sale_amount - sale_cost
WHERE gross_profit IS NULL;

-- 2.2 补充缺失品类
UPDATE t_htma_sale s
INNER JOIN t_htma_category_mapping m ON s.sku_code = m.sku_code
SET s.category = m.category
WHERE s.category IS NULL OR s.category = '';

-- 2.3 统一门店ID
UPDATE t_htma_sale SET store_id = '沈阳超级仓' WHERE store_id IS NULL OR store_id = '';

-- 2.4 剔除明显异常（销售额或成本为负）
UPDATE t_htma_sale SET sale_amount = 0 WHERE sale_amount < 0;
UPDATE t_htma_sale SET sale_cost = 0 WHERE sale_cost < 0;

-- -----------------------------------------------------
-- 3. 毛利表清洗
-- -----------------------------------------------------

-- 3.1 校验并修正毛利率 = 总毛利 / 总销售额
UPDATE t_htma_profit
SET profit_rate = CASE
  WHEN total_sale > 0 THEN total_profit / total_sale
  ELSE 0
END
WHERE profit_rate IS NULL OR total_sale > 0;

-- 3.2 统一门店ID
UPDATE t_htma_profit SET store_id = '沈阳超级仓' WHERE store_id IS NULL OR store_id = '';

-- -----------------------------------------------------
-- 4. 数据一致性校验视图（可选）
-- -----------------------------------------------------

CREATE OR REPLACE VIEW v_htma_data_check AS
SELECT
  '库存表' AS tbl_name,
  COUNT(*) AS row_count,
  MIN(data_date) AS min_date,
  MAX(data_date) AS max_date
FROM t_htma_stock
UNION ALL
SELECT '销售表', COUNT(*), MIN(data_date), MAX(data_date) FROM t_htma_sale
UNION ALL
SELECT '毛利表', COUNT(*), MIN(data_date), MAX(data_date) FROM t_htma_profit;

-- 查看校验结果
SELECT * FROM v_htma_data_check;

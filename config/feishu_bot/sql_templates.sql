-- 飞书机器人只读查询模板（说明用；实际执行语句在 feishu_bot_brain.py 中硬编码白名单，禁止拼接用户输入）
-- 部署建议：为机器人单独建 MySQL 账号，仅 GRANT SELECT ON htma_dashboard.* ...

-- 概览：各表行数 + 日期列（若存在）
-- SELECT COUNT(*) AS cnt, MIN(data_date) AS dmin, MAX(data_date) AS dmax FROM t_htma_sale;
-- SELECT COUNT(*) AS cnt, MIN(data_date) AS dmin, MAX(data_date) AS dmax FROM t_htma_stock;
-- SELECT COUNT(*) AS cnt, MIN(data_date) AS dmin, MAX(data_date) AS dmax FROM t_htma_profit;

-- 高库存示例（阈值由代码参数绑定，禁止字符串拼接）
-- SELECT product_name, sku_code, stock_qty, stock_amount, data_date
-- FROM t_htma_stock
-- WHERE stock_qty > %s
-- ORDER BY stock_qty DESC
-- LIMIT 15;

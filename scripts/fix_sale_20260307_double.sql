-- 修正 2026-03-07 销售数据因「销售汇总」累加导入导致的翻倍
-- 原因：此前销售汇总在未与日报同传时使用累加模式，同 (data_date, sku_code) 被加了两遍
-- 执行前可先查看当日汇总：SELECT SUM(sale_amount), SUM(sale_qty), COUNT(*) FROM t_htma_sale WHERE data_date = '2026-03-07';

UPDATE t_htma_sale
SET
  sale_qty    = sale_qty / 2,
  sale_amount = sale_amount / 2,
  sale_cost   = sale_cost / 2,
  gross_profit = gross_profit / 2
WHERE data_date = '2026-03-07';

-- 执行后校验：SELECT SUM(sale_amount), SUM(sale_qty), COUNT(*) FROM t_htma_sale WHERE data_date = '2026-03-07';

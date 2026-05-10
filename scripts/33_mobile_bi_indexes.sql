-- 经营分析小程序 API 性能：daily_category_stats 与 t_htma_sale 补充索引
-- 执行: mysql -h HOST -u USER -p htma_dashboard < scripts/33_mobile_bi_indexes.sql

USE htma_dashboard;

-- 月×店×大类 聚合走 DATE_FORMAT(ym) 时，辅助按日期区间过滤
SET @e := (
  SELECT IF(
    COUNT(*)=0,
    'CREATE INDEX idx_dcs_date_store ON daily_category_stats (data_date, store_id(16))',
    'SELECT 1'
  )
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'daily_category_stats' AND INDEX_NAME = 'idx_dcs_date_store'
);
-- MySQL 5.7: 动态执行需过程；这里直接可重复执行 Create（若已存在会报错，请忽略或手删重复）
-- CREATE INDEX idx_dcs_date_store ON daily_category_stats (data_date, store_id(16));

-- t_htma_sale：SKU 搜索（近 90 天 + 店）
-- CREATE INDEX idx_sale_date_store_sku ON t_htma_sale (data_date, store_id(16), sku_code(32));

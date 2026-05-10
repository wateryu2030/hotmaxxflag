-- 日×店×大类×中类预聚合（减轻 t_htma_sale 全表 GROUP BY）
-- 执行: mysql -h HOST -u USER -p DATABASE < scripts/27_daily_category_stats.sql
-- 刷新示例见 scripts/refresh_daily_category_stats.py

USE htma_dashboard;

CREATE TABLE IF NOT EXISTS daily_category_stats (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  store_id VARCHAR(32) NOT NULL COMMENT '门店',
  data_date DATE NOT NULL COMMENT '销售日',
  category_large_code VARCHAR(32) NOT NULL DEFAULT '' COMMENT '大类编码',
  category_large VARCHAR(128) NOT NULL DEFAULT '' COMMENT '大类名',
  category_mid_code VARCHAR(32) NOT NULL DEFAULT '' COMMENT '中类编码',
  category_mid VARCHAR(128) NOT NULL DEFAULT '' COMMENT '中类名',
  sale_qty DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '销量合计',
  sale_amount DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '销售额',
  sale_cost DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '成本',
  gross_profit DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '毛利',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_store_date_large_mid (store_id, data_date, category_large_code, category_mid_code),
  KEY idx_store_date (store_id, data_date),
  KEY idx_date (data_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='销售按日+店+大类+中类预聚合';

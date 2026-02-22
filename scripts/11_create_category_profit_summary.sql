-- =====================================================
-- 品类毛利汇总表：按品类聚合，供导出品类使用
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/11_create_category_profit_summary.sql
-- =====================================================

USE htma_dashboard;

-- 品类毛利汇总（按周期聚合，可定期刷新）
DROP TABLE IF EXISTS t_htma_category_profit;

CREATE TABLE t_htma_category_profit (
  id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  store_id            VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  category            VARCHAR(64)     NOT NULL COMMENT '品类/小类',
  category_large_code VARCHAR(32)     DEFAULT NULL,
  category_large      VARCHAR(64)     DEFAULT NULL COMMENT '大类',
  category_mid_code   VARCHAR(32)     DEFAULT NULL,
  category_mid        VARCHAR(64)     DEFAULT NULL COMMENT '中类',
  category_small_code VARCHAR(32)     DEFAULT NULL,
  category_small      VARCHAR(64)     DEFAULT NULL COMMENT '小类',
  total_sale          DECIMAL(14,2)   NOT NULL DEFAULT 0 COMMENT '总销售额',
  total_profit        DECIMAL(14,2)   NOT NULL DEFAULT 0 COMMENT '总毛利',
  profit_rate         DECIMAL(6,4)    DEFAULT NULL COMMENT '毛利率',
  sku_count           INT             DEFAULT 0 COMMENT 'SKU数',
  sale_count          INT             DEFAULT 0 COMMENT '销售笔数',
  period_start        DATE            DEFAULT NULL COMMENT '统计周期起',
  period_end          DATE            DEFAULT NULL COMMENT '统计周期止',
  sync_at             DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_store_cat (store_id, category),
  KEY idx_cat_large (category_large),
  KEY idx_cat_mid (category_mid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='品类毛利汇总-供导出品类';

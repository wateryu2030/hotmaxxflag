-- =====================================================
-- 商品主数据表：供导出、比价分析使用，具唯一性，有条码必记录
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/10_create_products_table.sql
-- =====================================================

USE htma_dashboard;

DROP TABLE IF EXISTS t_htma_products;

CREATE TABLE t_htma_products (
  id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  store_id            VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  sku_code            VARCHAR(64)     NOT NULL COMMENT '商品编码(唯一)',
  product_name        VARCHAR(128)    DEFAULT NULL COMMENT '品名',
  spec                VARCHAR(64)     DEFAULT NULL COMMENT '规格',
  barcode             VARCHAR(64)     DEFAULT NULL COMMENT '条码(有则必录,供比价)',
  brand_name          VARCHAR(64)     DEFAULT NULL COMMENT '品牌',
  category            VARCHAR(64)     DEFAULT NULL COMMENT '品类/小类',
  category_large_code VARCHAR(32)     DEFAULT NULL,
  category_large      VARCHAR(64)     DEFAULT NULL COMMENT '大类',
  category_mid_code   VARCHAR(32)     DEFAULT NULL,
  category_mid        VARCHAR(64)     DEFAULT NULL COMMENT '中类',
  category_small_code VARCHAR(32)     DEFAULT NULL,
  category_small      VARCHAR(64)     DEFAULT NULL COMMENT '小类',
  unit                VARCHAR(16)     DEFAULT NULL COMMENT '单位',
  sync_at             DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_store_sku (store_id, sku_code),
  KEY idx_barcode (barcode),
  KEY idx_category (category),
  KEY idx_cat_large (category_large),
  KEY idx_cat_mid (category_mid),
  KEY idx_cat_small (category_small)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品主数据-供导出与比价,条码必录';

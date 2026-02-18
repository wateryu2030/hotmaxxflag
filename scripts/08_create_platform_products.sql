-- =====================================================
-- 平台商品表 - 供比价与查询使用
-- 按大类、中类、小类分类，含规格、条码
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/08_create_platform_products.sql
-- =====================================================

USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_htma_platform_products (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  store_id        VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  sku_code        VARCHAR(64)     NOT NULL COMMENT 'SKU编码',
  product_name    VARCHAR(128)    DEFAULT NULL COMMENT '品名',
  raw_name        VARCHAR(128)    DEFAULT NULL COMMENT '原始品名',
  spec            VARCHAR(64)     DEFAULT NULL COMMENT '规格',
  barcode         VARCHAR(64)     DEFAULT NULL COMMENT '条码',
  brand_name      VARCHAR(64)     DEFAULT NULL COMMENT '品牌',
  category        VARCHAR(64)     DEFAULT NULL COMMENT '品类',
  category_large  VARCHAR(64)     DEFAULT NULL COMMENT '大类',
  category_mid    VARCHAR(64)     DEFAULT NULL COMMENT '中类',
  category_small  VARCHAR(64)     DEFAULT NULL COMMENT '小类',
  category_large_code VARCHAR(32) DEFAULT NULL,
  category_mid_code   VARCHAR(32) DEFAULT NULL,
  category_small_code VARCHAR(32) DEFAULT NULL,
  unit_price      DECIMAL(12,2)   DEFAULT NULL COMMENT '当前售价',
  sale_qty        DECIMAL(12,2)   DEFAULT 0 COMMENT '近30天销量',
  sale_amount     DECIMAL(14,2)   DEFAULT 0 COMMENT '近30天销售额',
  gross_profit    DECIMAL(14,2)   DEFAULT 0 COMMENT '近30天毛利',
  sync_at         DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '同步时间',
  UNIQUE KEY uk_store_sku (store_id, sku_code),
  KEY idx_cat_large (category_large),
  KEY idx_cat_mid (category_mid),
  KEY idx_cat_small (category_small),
  KEY idx_sync (sync_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='平台商品清单（按大类/中类/小类，供比价查询）';

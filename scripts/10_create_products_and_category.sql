-- =====================================================
-- 商品主表 + 品类毛利表（数据导入时同步，供导出与比价使用）
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/10_create_products_and_category.sql
-- =====================================================

USE htma_dashboard;

-- 1. 商品主表 t_htma_products（唯一性：store_id+sku_code，有条码必录，供比价）
CREATE TABLE IF NOT EXISTS t_htma_products (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  store_id        VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  sku_code        VARCHAR(64)     NOT NULL COMMENT 'SKU编码（唯一）',
  product_name    VARCHAR(128)    DEFAULT NULL COMMENT '品名',
  raw_name        VARCHAR(128)    DEFAULT NULL COMMENT '原始品名',
  spec            VARCHAR(64)     DEFAULT NULL COMMENT '规格',
  barcode         VARCHAR(64)     DEFAULT NULL COMMENT '条码（有则必录，供比价）',
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
  sync_at         DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_store_sku (store_id, sku_code),
  KEY idx_barcode (barcode),
  KEY idx_cat_large (category_large),
  KEY idx_cat_mid (category_mid),
  KEY idx_cat_small (category_small)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品主表（唯一性、条码供比价）';

-- 2. 品类毛利表 t_htma_category（品类维度汇总，供导出与分析）
CREATE TABLE IF NOT EXISTS t_htma_category (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  store_id        VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  category        VARCHAR(64)     NOT NULL COMMENT '品类（小类）',
  category_large  VARCHAR(64)     DEFAULT NULL COMMENT '大类',
  category_mid    VARCHAR(64)     DEFAULT NULL COMMENT '中类',
  category_small  VARCHAR(64)     DEFAULT NULL COMMENT '小类',
  category_large_code VARCHAR(32) DEFAULT NULL,
  category_mid_code   VARCHAR(32) DEFAULT NULL,
  category_small_code VARCHAR(32) DEFAULT NULL,
  total_sale      DECIMAL(14,2)   DEFAULT 0 COMMENT '总销售额',
  total_profit    DECIMAL(14,2)   DEFAULT 0 COMMENT '总毛利',
  profit_rate     DECIMAL(6,4)    DEFAULT NULL COMMENT '毛利率',
  product_count   INT             DEFAULT 0 COMMENT '商品数',
  sale_count      INT             DEFAULT 0 COMMENT '销售笔数',
  period_start    DATE            DEFAULT NULL COMMENT '统计周期起',
  period_end      DATE            DEFAULT NULL COMMENT '统计周期止',
  sync_at         DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_store_cat (store_id, category),
  KEY idx_cat_large (category_large),
  KEY idx_cat_mid (category_mid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='品类毛利表（供导出与分析）';

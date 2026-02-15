-- =====================================================
-- 好特卖超级仓 - 库存表重建（库存查询_默认格式）
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/05_create_stock_table_v2.sql
-- 依据：库存查询_默认 Excel 结构
-- =====================================================

USE htma_dashboard;

DROP TABLE IF EXISTS t_htma_stock;

CREATE TABLE t_htma_stock (
  id                    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  data_date             DATE            NOT NULL COMMENT '库存日期/报表日期 YYYY-MM-DD',
  sku_code              VARCHAR(64)     NOT NULL COMMENT '货号/商品编码',
  store_id              VARCHAR(32)     DEFAULT '沈阳超级仓' COMMENT '门店ID',
  warehouse_code        VARCHAR(32)     DEFAULT NULL COMMENT '仓库编码',
  warehouse_name        VARCHAR(128)    DEFAULT NULL COMMENT '仓库名称',
  category              VARCHAR(64)     DEFAULT NULL COMMENT '品类',
  category_large_code   VARCHAR(32)     DEFAULT NULL COMMENT '大类编码',
  category_large        VARCHAR(64)     DEFAULT NULL COMMENT '大类名称',
  category_mid_code     VARCHAR(32)     DEFAULT NULL COMMENT '中类编码',
  category_mid          VARCHAR(64)     DEFAULT NULL COMMENT '中类名称',
  category_small_code   VARCHAR(32)     DEFAULT NULL COMMENT '小类编码',
  category_small        VARCHAR(64)     DEFAULT NULL COMMENT '小类名称',
  spec                  VARCHAR(64)     DEFAULT NULL COMMENT '规格',
  location_name         VARCHAR(64)     DEFAULT NULL COMMENT '库位名称',
  brand_name            VARCHAR(64)     DEFAULT NULL COMMENT '品牌',
  unit                  VARCHAR(16)     DEFAULT NULL COMMENT '单位',
  product_code          VARCHAR(64)     DEFAULT NULL COMMENT '品号',
  stock_qty             DECIMAL(12, 2)  NOT NULL DEFAULT 0 COMMENT '库存数量',
  avg_price             DECIMAL(14, 4)  DEFAULT NULL COMMENT '平均价',
  stock_amount          DECIMAL(14, 2)  DEFAULT 0 COMMENT '库存总金额',
  aging                 DECIMAL(10, 4)  DEFAULT NULL COMMENT '账龄',
  last_change_date      DATETIME        DEFAULT NULL COMMENT '上次变动日期',
  avg_inbound_price     DECIMAL(14, 4)  DEFAULT NULL COMMENT '平均入库价',
  product_status        VARCHAR(32)     DEFAULT NULL COMMENT 'SKU商品状态',
  barcode               VARCHAR(64)     DEFAULT NULL COMMENT '条码',
  product_name          VARCHAR(128)    DEFAULT NULL COMMENT '商品名称',
  category_name         VARCHAR(64)     DEFAULT NULL COMMENT '类别名称(兼容)',
  created_at            DATETIME        DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_date_sku (data_date, sku_code),
  KEY idx_data_date (data_date),
  KEY idx_sku_code (sku_code),
  KEY idx_category (category),
  KEY idx_category_large (category_large_code),
  KEY idx_store (store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='好特卖-库存表(库存查询_默认格式)';

SELECT 'Done. t_htma_stock 已按库存查询_默认格式重建' AS msg;

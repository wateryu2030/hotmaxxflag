-- =====================================================
-- 好特卖超级仓 - 数据看板 建表脚本
-- 数据库: MySQL 5.7+
-- 字符集: utf8mb4
-- 说明: 创建库存表、销售表、毛利表，供 JimuReport 看板使用
-- =====================================================

-- 创建数据库（如已存在可跳过）
CREATE DATABASE IF NOT EXISTS htma_dashboard
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE htma_dashboard;

-- -----------------------------------------------------
-- 1. 库存表 t_htma_stock
-- -----------------------------------------------------
DROP TABLE IF EXISTS t_htma_stock;

CREATE TABLE t_htma_stock (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  data_date     DATE            NOT NULL COMMENT '库存日期 YYYY-MM-DD',
  sku_code      VARCHAR(64)     NOT NULL COMMENT '商品编码',
  category      VARCHAR(64)     DEFAULT NULL COMMENT '品类',
  stock_qty     DECIMAL(12, 2)  NOT NULL DEFAULT 0 COMMENT '库存数量',
  stock_amount  DECIMAL(14, 2)  DEFAULT 0 COMMENT '库存金额',
  store_id      VARCHAR(32)     DEFAULT '沈阳超级仓' COMMENT '门店ID',
  created_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_date_sku (data_date, sku_code),
  KEY idx_data_date (data_date),
  KEY idx_sku_code (sku_code),
  KEY idx_category (category),
  KEY idx_store (store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='好特卖-库存表';

-- -----------------------------------------------------
-- 2. 销售表 t_htma_sale
-- -----------------------------------------------------
DROP TABLE IF EXISTS t_htma_sale;

CREATE TABLE t_htma_sale (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  data_date     DATE            NOT NULL COMMENT '销售日期 YYYY-MM-DD',
  sku_code      VARCHAR(64)     NOT NULL COMMENT '商品编码',
  category      VARCHAR(64)     DEFAULT NULL COMMENT '品类',
  sale_qty      DECIMAL(12, 2)  NOT NULL DEFAULT 0 COMMENT '销售数量',
  sale_amount   DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '销售额',
  sale_cost     DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '销售成本',
  gross_profit  DECIMAL(14, 2)  DEFAULT NULL COMMENT '单品毛利(销售额-销售成本)',
  store_id      VARCHAR(32)     DEFAULT '沈阳超级仓' COMMENT '门店ID',
  created_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_date_sku (data_date, sku_code),
  KEY idx_data_date (data_date),
  KEY idx_sku_code (sku_code),
  KEY idx_category (category),
  KEY idx_store (store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='好特卖-销售表';

-- -----------------------------------------------------
-- 3. 毛利表 t_htma_profit
-- -----------------------------------------------------
DROP TABLE IF EXISTS t_htma_profit;

CREATE TABLE t_htma_profit (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  data_date     DATE            NOT NULL COMMENT '日期 YYYY-MM-DD',
  category      VARCHAR(64)     DEFAULT NULL COMMENT '品类',
  total_sale    DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '总销售额',
  total_profit  DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '总毛利',
  profit_rate   DECIMAL(6, 4)   DEFAULT NULL COMMENT '毛利率(总毛利/总销售额)',
  store_id      VARCHAR(32)     DEFAULT '沈阳超级仓' COMMENT '门店ID',
  created_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_date_category_store (data_date, category, store_id),
  KEY idx_data_date (data_date),
  KEY idx_category (category),
  KEY idx_store (store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='好特卖-毛利表';

-- -----------------------------------------------------
-- 4. 品类主数据表（可选，用于补充缺失品类）
-- -----------------------------------------------------
DROP TABLE IF EXISTS t_htma_category_mapping;

CREATE TABLE t_htma_category_mapping (
  id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  sku_code      VARCHAR(64)     NOT NULL UNIQUE COMMENT '商品编码',
  category      VARCHAR(64)     NOT NULL COMMENT '品类',
  sub_category  VARCHAR(64)     DEFAULT NULL COMMENT '子品类',
  created_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,
  KEY idx_sku (sku_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品-品类映射表';

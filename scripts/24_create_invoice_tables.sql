-- =====================================================
-- 发票比对：发票明细表 + 比对结果表
-- 依据：docs/发票比对功能说明与表设计.md
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/24_create_invoice_tables.sql
-- =====================================================

USE htma_dashboard;

-- -----------------------------------------------------
-- 1. 发票明细表 t_htma_invoice_detail（按月、按三级类别存导入的发票汇总）
-- -----------------------------------------------------
DROP TABLE IF EXISTS t_htma_invoice_detail;

CREATE TABLE t_htma_invoice_detail (
  id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  period_month        DATE            NOT NULL COMMENT '账期月份 如 2025-12-01 表示2025年12月',
  category_small_code VARCHAR(32)     DEFAULT NULL COMMENT '三级类别编码(小类编码,1月有/12月可空)',
  category_small_name VARCHAR(128)   NOT NULL COMMENT '三级类别名称',
  tax_class_code      VARCHAR(32)     DEFAULT NULL COMMENT '税收分类编码',
  tax_rate            DECIMAL(5, 4)   NOT NULL DEFAULT 0 COMMENT '税率 如0.13',
  sale_qty            DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '开票销售数量',
  invoice_amount      DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '开票金额(含税)',
  store_id            VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓' COMMENT '门店',
  created_at          DATETIME        DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_period_store_category (period_month, store_id, category_small_name(64)),
  KEY idx_period (period_month),
  KEY idx_category_name (category_small_name(64)),
  KEY idx_category_code (category_small_code),
  KEY idx_store (store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='发票明细-按月按三级类别导入';

-- -----------------------------------------------------
-- 2. 比对结果表 t_htma_invoice_compare_result（可选，存每次比对结果）
-- -----------------------------------------------------
DROP TABLE IF EXISTS t_htma_invoice_compare_result;

CREATE TABLE t_htma_invoice_compare_result (
  id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  period_month        DATE            NOT NULL COMMENT '账期月份',
  category_small_code VARCHAR(32)     DEFAULT NULL COMMENT '三级类别编码',
  category_small_name VARCHAR(128)   NOT NULL COMMENT '三级类别名称',
  system_sale_amount  DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '系统销售额',
  system_sale_qty     DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '系统销售数量',
  invoice_amount      DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '开票金额',
  invoice_sale_qty    DECIMAL(14, 2)  NOT NULL DEFAULT 0 COMMENT '开票数量',
  amount_diff         DECIMAL(14, 2)  DEFAULT NULL COMMENT '收入差额(系统-开票)',
  system_tax_amount   DECIMAL(14, 2)  DEFAULT NULL COMMENT '系统推算税负额',
  invoice_tax_amount  DECIMAL(14, 2)  DEFAULT NULL COMMENT '发票税负额',
  tax_diff            DECIMAL(14, 2)  DEFAULT NULL COMMENT '税负差额',
  store_id            VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  created_at          DATETIME        DEFAULT CURRENT_TIMESTAMP COMMENT '比对时间',
  KEY idx_period (period_month),
  KEY idx_category_name (category_small_name(64)),
  KEY idx_store (store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='发票比对结果-收入与税负差额';

SELECT 'Done. t_htma_invoice_detail, t_htma_invoice_compare_result 已创建' AS msg;

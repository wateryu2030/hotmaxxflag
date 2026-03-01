-- =====================================================
-- 税率负担表：用于统计税务负担情况，数据来自「税率负担表」Excel
-- 附表列：编码、名称、毛利率(0-1)、前台显示、微小店状态、税收分类编码、税率
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/12_create_tax_burden_table.sql
-- =====================================================

USE htma_dashboard;

DROP TABLE IF EXISTS t_htma_tax_burden;

CREATE TABLE t_htma_tax_burden (
  id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  code            VARCHAR(32)   NOT NULL COMMENT '编码',
  name            VARCHAR(128)  NOT NULL COMMENT '名称',
  gross_margin    DECIMAL(5, 4) NOT NULL DEFAULT 0 COMMENT '毛利率(0-1)',
  front_display   VARCHAR(8)    DEFAULT '是' COMMENT '前台显示 是/否',
  minishop_status VARCHAR(32)   DEFAULT NULL COMMENT '微小店状态',
  tax_class_code  VARCHAR(32)   DEFAULT NULL COMMENT '税收分类编码',
  tax_rate        DECIMAL(5, 4) NOT NULL DEFAULT 0 COMMENT '税率',
  created_at      DATETIME      DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_code (code),
  KEY idx_tax_rate (tax_rate),
  KEY idx_tax_class_code (tax_class_code),
  KEY idx_front_display (front_display)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='税率负担表-税务负担统计';

SELECT 'Done. t_htma_tax_burden 已创建' AS msg;

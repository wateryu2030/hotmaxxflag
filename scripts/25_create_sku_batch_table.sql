-- =====================================================
-- 供销社「红背篓」等渠道选品：SKU 批次/效期（方案 A）
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/25_create_sku_batch_table.sql
-- 说明: 按批次维护生产日期/到期日与数量，选品导出时取 MIN(到期日) 作为最早到期
-- =====================================================

USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_htma_sku_batch (
  id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  store_id          VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓' COMMENT '门店',
  sku_code          VARCHAR(64)     NOT NULL COMMENT '货号',
  batch_no          VARCHAR(64)     DEFAULT NULL COMMENT '批次号/供应商批次',
  production_date   DATE            DEFAULT NULL COMMENT '生产日期',
  expiry_date       DATE            NOT NULL COMMENT '到期日',
  qty               DECIMAL(14, 4)  NOT NULL DEFAULT 0 COMMENT '本批次在库数量',
  remark            VARCHAR(512)    DEFAULT NULL COMMENT '备注',
  created_at        DATETIME        DEFAULT CURRENT_TIMESTAMP,
  updated_at        DATETIME        DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_store_sku (store_id, sku_code),
  KEY idx_expiry (expiry_date),
  KEY idx_sku_expiry (sku_code, expiry_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='SKU批次效期(渠道选品)';

SELECT 'Done. t_htma_sku_batch 已创建' AS msg;

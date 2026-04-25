-- 全量发票导出（税务平台 xlsx：信息汇总表=明细行，发票基础信息=按票汇总）
-- mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/26_full_invoice_raw_tables.sql

USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_htma_full_invoice_import_batch (
  id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  period_month    DATE            NOT NULL COMMENT '账期月份 如 2025-12-01',
  store_id        VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  file_name       VARCHAR(512)    DEFAULT NULL,
  line_row_count  INT             NOT NULL DEFAULT 0,
  header_row_count INT            NOT NULL DEFAULT 0,
  created_at      DATETIME        DEFAULT CURRENT_TIMESTAMP,
  KEY idx_period_store (period_month, store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='全量发票导入批次';

CREATE TABLE IF NOT EXISTS t_htma_full_invoice_header_raw (
  id                    BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  batch_id              BIGINT UNSIGNED NOT NULL,
  period_month          DATE            NOT NULL,
  store_id              VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  seq_no                INT             DEFAULT NULL COMMENT '序号',
  invoice_code          VARCHAR(64)     DEFAULT NULL COMMENT '发票代码',
  invoice_no            VARCHAR(64)     DEFAULT NULL COMMENT '发票号码',
  digital_invoice_no    VARCHAR(64)     NOT NULL COMMENT '数电发票号码',
  seller_tax_id         VARCHAR(32)     DEFAULT NULL,
  seller_name           VARCHAR(256)    DEFAULT NULL,
  buyer_tax_id          VARCHAR(32)     DEFAULT NULL,
  buyer_name            VARCHAR(256)    DEFAULT NULL,
  invoice_datetime      DATETIME        DEFAULT NULL,
  amount_excl_tax       DECIMAL(16, 4)  NOT NULL DEFAULT 0 COMMENT '金额(不含税)',
  tax_amount            DECIMAL(16, 4)  NOT NULL DEFAULT 0,
  total_incl_tax        DECIMAL(16, 4)  NOT NULL DEFAULT 0 COMMENT '价税合计',
  invoice_source        VARCHAR(128)    DEFAULT NULL,
  invoice_type          VARCHAR(128)    DEFAULT NULL,
  invoice_status        VARCHAR(64)     DEFAULT NULL,
  is_positive_invoice   VARCHAR(16)     DEFAULT NULL,
  risk_level            VARCHAR(64)     DEFAULT NULL,
  drawer                VARCHAR(64)     DEFAULT NULL,
  remark                TEXT,
  created_at            DATETIME        DEFAULT CURRENT_TIMESTAMP,
  KEY idx_batch (batch_id),
  KEY idx_period_digital (period_month, digital_invoice_no(32)),
  KEY idx_store_period (store_id, period_month),
  CONSTRAINT fk_fi_hdr_batch FOREIGN KEY (batch_id) REFERENCES t_htma_full_invoice_import_batch (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='全量发票-票头汇总(发票基础信息sheet)';

CREATE TABLE IF NOT EXISTS t_htma_full_invoice_line_raw (
  id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  batch_id                BIGINT UNSIGNED NOT NULL,
  period_month            DATE            NOT NULL,
  store_id                VARCHAR(32)     NOT NULL DEFAULT '沈阳超级仓',
  seq_no                  INT             DEFAULT NULL,
  invoice_code            VARCHAR(64)     DEFAULT NULL,
  invoice_no              VARCHAR(64)     DEFAULT NULL,
  digital_invoice_no      VARCHAR(64)     NOT NULL,
  seller_tax_id           VARCHAR(32)     DEFAULT NULL,
  seller_name             VARCHAR(256)    DEFAULT NULL,
  buyer_tax_id            VARCHAR(32)     DEFAULT NULL,
  buyer_name              VARCHAR(256)    DEFAULT NULL,
  invoice_datetime        DATETIME        DEFAULT NULL,
  tax_class_code          VARCHAR(32)     DEFAULT NULL COMMENT '税收分类编码',
  specific_business_type  VARCHAR(128)    DEFAULT NULL,
  goods_name              VARCHAR(512)    DEFAULT NULL COMMENT '货物或应税劳务名称',
  spec_model              VARCHAR(256)    DEFAULT NULL COMMENT '规格型号',
  unit_name               VARCHAR(32)     DEFAULT NULL,
  qty                     DECIMAL(18, 6)  DEFAULT NULL,
  unit_price              DECIMAL(18, 8)  DEFAULT NULL,
  amount_excl_tax         DECIMAL(16, 4)  NOT NULL DEFAULT 0,
  tax_rate_raw            VARCHAR(32)     DEFAULT NULL COMMENT '税率原文如13%',
  tax_amount              DECIMAL(16, 4)  NOT NULL DEFAULT 0,
  total_incl_tax          DECIMAL(16, 4)  NOT NULL DEFAULT 0,
  invoice_source          VARCHAR(128)    DEFAULT NULL,
  invoice_type            VARCHAR(128)    DEFAULT NULL,
  invoice_status          VARCHAR(64)     DEFAULT NULL,
  is_positive_invoice     VARCHAR(16)     DEFAULT NULL,
  risk_level              VARCHAR(64)     DEFAULT NULL,
  drawer                  VARCHAR(64)     DEFAULT NULL,
  remark                  TEXT,
  goods_norm_key          VARCHAR(256)    DEFAULT NULL COMMENT '归一化品名键，用于与销售比对',
  created_at              DATETIME        DEFAULT CURRENT_TIMESTAMP,
  KEY idx_batch (batch_id),
  KEY idx_digital (digital_invoice_no(32)),
  KEY idx_period (period_month),
  KEY idx_goods_norm (goods_norm_key(64)),
  CONSTRAINT fk_fi_line_batch FOREIGN KEY (batch_id) REFERENCES t_htma_full_invoice_import_batch (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='全量发票-明细行(信息汇总表sheet)';

SELECT 'Done. t_htma_full_invoice_* 已就绪' AS msg;

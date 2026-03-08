-- -----------------------------------------------------
-- 人力分析：销售类目–人力岗位映射（经营/管理拆分、生效日期）
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/16_create_labor_category_mapping.sql
-- -----------------------------------------------------
USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_htma_labor_category_mapping (
  id                   BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  sales_category       VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '销售大类目(category_large); 管理时可为空',
  cost_type            VARCHAR(16)   NOT NULL COMMENT 'operational=经营, management=管理',
  labor_position_name   VARCHAR(64)   NOT NULL COMMENT '人力岗位名(position_name)',
  match_type           VARCHAR(16)   NOT NULL DEFAULT 'prefix' COMMENT 'exact=精确, prefix=前缀',
  effective_from       DATE          DEFAULT NULL COMMENT '生效开始日期，NULL=不限',
  effective_to         DATE          DEFAULT NULL COMMENT '生效结束日期，NULL=不限',
  sort_order           INT           NOT NULL DEFAULT 0,
  created_at           DATETIME      DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_sales_cat (sales_category),
  KEY idx_cost_type (cost_type),
  KEY idx_effective (effective_from, effective_to),
  KEY idx_position (labor_position_name(32))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人力分析-销售类目与人力岗位映射';

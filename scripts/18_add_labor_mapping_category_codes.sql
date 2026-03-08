-- 人力分析映射表：增加大类代码、中类代码，与看板一致按代码匹配（参考 /api/categories）
-- 执行: mysql ... htma_dashboard < scripts/18_add_labor_mapping_category_codes.sql
USE htma_dashboard;

ALTER TABLE t_htma_labor_category_mapping
  ADD COLUMN sales_category_large_code VARCHAR(64) NOT NULL DEFAULT '' COMMENT '销售大类代码(category_large_code)' AFTER sales_category;
ALTER TABLE t_htma_labor_category_mapping
  ADD COLUMN sales_category_mid_code VARCHAR(64) NOT NULL DEFAULT '' COMMENT '销售中类代码(category_mid_code)' AFTER sales_category_large_code;

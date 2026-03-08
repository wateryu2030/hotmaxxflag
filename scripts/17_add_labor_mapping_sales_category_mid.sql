-- 人力分析映射表增加销售中类字段（建立大类+中类对应关系）
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/17_add_labor_mapping_sales_category_mid.sql
USE htma_dashboard;

-- 增加销售中类字段（若已存在会报错，可忽略；部署脚本 2>/dev/null 会吞掉）
ALTER TABLE t_htma_labor_category_mapping
  ADD COLUMN sales_category_mid VARCHAR(64) NOT NULL DEFAULT '' COMMENT '销售中类(category_mid)' AFTER sales_category;

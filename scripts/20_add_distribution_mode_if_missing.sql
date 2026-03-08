-- 若 t_htma_product_master 缺少 distribution_mode 列则添加
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/20_add_distribution_mode_if_missing.sql

USE htma_dashboard;

SET @col_exists = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 't_htma_product_master'
    AND COLUMN_NAME = 'distribution_mode'
);

SET @sql = IF(@col_exists = 0,
  'ALTER TABLE t_htma_product_master ADD COLUMN distribution_mode VARCHAR(32) DEFAULT NULL COMMENT ''经销方式(购销/代销等)'' AFTER product_type',
  'SELECT ''distribution_mode 列已存在'' AS msg'
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

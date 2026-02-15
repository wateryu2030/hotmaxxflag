-- 修复 chartList config 导致 "illegal input, offset 1, char {" 解析错误
-- 将 config:"{}" 改为 config:"" 或移除 config，避免 JimuReport 解析失败
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/fix_htma_chart_config.sql

USE jimureport;
SET NAMES utf8mb4;

-- 将 chartList 中 "config":"{}" 替换为 "config":""
UPDATE jimu_report SET json_str = REPLACE(json_str, '"config":"{}"', '"config":""')
WHERE id = 'htma_dash_shenyang_001';

SELECT 'Done. 已修复 chart config' AS msg;

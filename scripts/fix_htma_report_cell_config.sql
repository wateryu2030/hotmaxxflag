-- 修复 htma 报表 cellTextJson 为 null 导致的 NPE
-- 为数据行单元格添加 loopBlock、config、rendered 等必要属性
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/fix_htma_report_cell_config.sql

USE jimureport;
SET NAMES utf8mb4;

-- 更新报表 json_str，为 row 1 的 cells 添加 loopBlock、config、rendered
UPDATE jimu_report SET json_str = JSON_SET(
  json_str,
  '$.rows.1.cells.0.loopBlock', 1,
  '$.rows.1.cells.0.config', '',
  '$.rows.1.cells.0.rendered', '',
  '$.rows.1.cells.1.loopBlock', 1,
  '$.rows.1.cells.1.config', '',
  '$.rows.1.cells.1.rendered', '',
  '$.rows.1.cells.2.loopBlock', 1,
  '$.rows.1.cells.2.config', '',
  '$.rows.1.cells.2.rendered', '',
  '$.rows.1.cells.3.loopBlock', 1,
  '$.rows.1.cells.3.config', '',
  '$.rows.1.cells.3.rendered', '',
  '$.rows.1.cells.4.loopBlock', 1,
  '$.rows.1.cells.4.config', '',
  '$.rows.1.cells.4.rendered', '',
  '$.rows.1.cells.5.loopBlock', 1,
  '$.rows.1.cells.5.config', '',
  '$.rows.1.cells.5.rendered', ''
)
WHERE id = '8946110000000000001'
  AND JSON_EXTRACT(json_str, '$.rows.1.cells.0.loopBlock') IS NULL;

SELECT id, name, 'Updated' AS status FROM jimu_report WHERE id = '8946110000000000001';

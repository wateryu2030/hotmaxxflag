-- 修复好特卖运营看板：补充 jmsheet 所需字段，避免 TypeError: Cannot convert undefined or null to object
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/fix_htma_dashboard_jmsheet.sql

USE jimureport;

SET NAMES utf8mb4;

-- 为图表报表补充 rows/cols/area 等，使 jmsheet 渲染时有合法对象可访问
UPDATE jimu_report SET json_str = JSON_SET(
  COALESCE(json_str, '{}'),
  '$.rows', JSON_OBJECT('0', JSON_OBJECT('cells', JSON_OBJECT('0', JSON_OBJECT('text', '好特卖沈阳超级仓运营看板')), 'height', 40)),
  '$.cols', JSON_OBJECT('0', JSON_OBJECT('width', 100), 'len', 100),
  '$.area', JSON_OBJECT('sri', 0, 'sci', 0, 'eri', 0, 'eci', 0, 'width', 100, 'height', 100),
  '$.styles', JSON_OBJECT(),
  '$.merges', JSON_ARRAY(),
  '$.printConfig', JSON_OBJECT('paper', 'A4', 'width', 210, 'height', 297, 'definition', 1, 'isBackend', 0, 'marginX', 10, 'marginY', 10, 'layout', 'portrait')
)
WHERE id = 'htma_dash_shenyang_001';

SELECT 'Done. 已补充 jmsheet 所需字段' AS msg;

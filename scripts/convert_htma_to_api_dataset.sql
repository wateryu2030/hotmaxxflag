-- 将好特卖报表改为 API 数据源，绕过 SQL 数据集的 cellTextJson NPE
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/convert_htma_to_api_dataset.sql

USE jimureport;
SET NAMES utf8mb4;

-- 删除原 SQL 数据集
DELETE FROM jimu_report_db_field WHERE jimu_report_db_id = '8946110000000000002';
DELETE FROM jimu_report_db_param WHERE jimu_report_head_id = '8946110000000000002';
DELETE FROM jimu_report_db WHERE id = '8946110000000000002';

-- 新增 API 数据集 htma_profit
INSERT INTO jimu_report_db (
  id, jimu_report_id, create_by, create_time, update_by, update_time,
  db_code, db_ch_name, db_type, api_url, is_list, is_page,
  db_source, db_source_type
) VALUES (
  '8946110000000000002',
  '8946110000000000001',
  'admin', NOW(), NULL, NULL,
  'htma_profit', '好特卖毛利汇总', '1',
  'http://127.0.0.1:8085/jmreport/api-proxy/htma/profit?pageSize=''${pageSize}''&pageNo=''${pageNo}''',
  '1', '1',
  NULL, NULL
);

-- 数据集字段（API 返回 data 数组，字段名需与 JSON 一致）
INSERT INTO jimu_report_db_field (id, create_by, create_time, jimu_report_db_id, field_name, field_text, order_num) VALUES
('8946110000000000011', 'admin', NOW(), '8946110000000000002', 'data_date', '日期', 1),
('8946110000000000012', 'admin', NOW(), '8946110000000000002', 'category', '品类', 2),
('8946110000000000013', 'admin', NOW(), '8946110000000000002', 'total_sale', '总销售额', 3),
('8946110000000000014', 'admin', NOW(), '8946110000000000002', 'total_profit', '总毛利', 4),
('8946110000000000015', 'admin', NOW(), '8946110000000000002', 'profit_rate', '毛利率', 5),
('8946110000000000016', 'admin', NOW(), '8946110000000000002', 'store_id', '门店', 6);

-- 分页参数
INSERT INTO jimu_report_db_param VALUES
('8946110000000000021', '8946110000000000002', 'pageSize', 'pageSize', '20', 1, NULL, NOW(), NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL),
('8946110000000000022', '8946110000000000002', 'pageNo', 'pageNo', '1', 2, NULL, NOW(), NULL, NULL, 0, NULL, NULL, NULL, NULL, NULL);

SELECT 'Converted htma report to API dataset' AS status;

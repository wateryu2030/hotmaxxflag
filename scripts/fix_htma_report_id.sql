-- 将好特卖报表 id 改为数字格式，避免 /jmreport/desreport/{id} 报 404（框架只认数字 id）
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/fix_htma_report_id.sql

USE jimureport;

SET NAMES utf8mb4;

-- 删除旧记录（字符串 id）
DELETE FROM jimu_report_db_field WHERE jimu_report_db_id IN ('htma_profit_db_01','8946110000000000002');
DELETE FROM jimu_report_db WHERE id = 'htma_profit_db_01' OR jimu_report_id IN ('8946110000000000001','9946110000000000001');
DELETE FROM jimu_report WHERE id IN ('htma_profit_report_01','9946110000000000001','8946110000000000001');

-- 报表主表（使用 19 位数字 id）
INSERT INTO `jimu_report` (
  `id`, `code`, `name`, `note`, `status`, `type`, `json_str`,
  `api_url`, `thumb`, `create_by`, `create_time`, `update_by`, `update_time`,
  `del_flag`, `api_method`, `api_code`, `template`, `view_count`, `css_str`, `js_str`, `py_str`,
  `tenant_id`, `update_count`, `submit_form`, `is_multi_sheet`
) VALUES (
  '8946110000000000001',
  'htma_profit_001',
  '好特卖销售明细',
  '好特卖超级仓-毛利表数据绑定',
  NULL,
  '984272091947253760',
  '{"loopBlockList":[{"sci":0,"sri":1,"eci":5,"eri":1,"index":1,"db":"htma_profit"}],"printConfig":{"paper":"A4","width":210,"height":297,"definition":1,"isBackend":false,"marginX":10,"marginY":10,"layout":"portrait"},"hidden":{"rows":[],"cols":[]},"dbexps":[],"dicts":[],"freeze":"A1","dataRectWidth":600,"autofilter":{},"validations":[],"cols":{"0":{"width":90},"1":{"width":80},"2":{"width":100},"3":{"width":100},"4":{"width":80},"5":{"width":100},"len":100},"area":{"sri":1,"sci":0,"eri":1,"eci":5,"width":100,"height":25},"pyGroupEngine":false,"excel_config_id":"8946110000000000001","hiddenCells":[],"zonedEditionList":[],"rows":{"0":{"cells":{"0":{"text":"日期"},"1":{"text":"品类"},"2":{"text":"总销售额"},"3":{"text":"总毛利"},"4":{"text":"毛利率"},"5":{"text":"门店"},"height":25}},"1":{"cells":{"0":{"text":"#{htma_profit.data_date}","loopBlock":1,"config":"","rendered":""},"1":{"text":"#{htma_profit.category}","loopBlock":1,"config":"","rendered":""},"2":{"text":"#{htma_profit.total_sale}","loopBlock":1,"config":"","rendered":""},"3":{"text":"#{htma_profit.total_profit}","loopBlock":1,"config":"","rendered":""},"4":{"text":"#{htma_profit.profit_rate}","loopBlock":1,"config":"","rendered":""},"5":{"text":"#{htma_profit.store_id}","loopBlock":1,"config":"","rendered":""}},"height":25},"len":200},"rpbar":{"show":true,"pageSize":"","btnList":[]}}',
  NULL, NULL, 'admin', NOW(), 'admin', NOW(),
  0, NULL, NULL, 1, 0, NULL, NULL, NULL, NULL, 0, 0, NULL
);

-- 数据集
INSERT INTO `jimu_report_db` (
  `id`, `jimu_report_id`, `create_by`, `create_time`, `update_by`, `update_time`,
  `db_code`, `db_ch_name`, `db_type`, `db_dyn_sql`, `db_key`, `is_list`, `is_page`,
  `db_source`, `db_source_type`
) VALUES (
  '8946110000000000002',
  '8946110000000000001',
  'admin', NOW(), NULL, NULL,
  'htma_profit', '好特卖毛利汇总', '0',
  'SELECT data_date, category, total_sale, total_profit, profit_rate, store_id FROM t_htma_profit ORDER BY data_date, category',
  'htma_report_001', '1', '0', 'htma_report_001', 'MYSQL'
);

-- 数据集字段
INSERT INTO `jimu_report_db_field` (`id`, `create_by`, `create_time`, `jimu_report_db_id`, `field_name`, `field_text`, `order_num`) VALUES
('8946110000000000011', 'admin', NOW(), '8946110000000000002', 'data_date', '日期', 1),
('8946110000000000012', 'admin', NOW(), '8946110000000000002', 'category', '品类', 2),
('8946110000000000013', 'admin', NOW(), '8946110000000000002', 'total_sale', '总销售额', 3),
('8946110000000000014', 'admin', NOW(), '8946110000000000002', 'total_profit', '总毛利', 4),
('8946110000000000015', 'admin', NOW(), '8946110000000000002', 'profit_rate', '毛利率', 5),
('8946110000000000016', 'admin', NOW(), '8946110000000000002', 'store_id', '门店', 6);

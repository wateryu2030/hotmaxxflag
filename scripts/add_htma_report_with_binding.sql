-- 好特卖毛利表报表：带数据绑定的模板 + 数据集，直接插入后即可在 JimuReport 中预览出数
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/add_htma_report_with_binding.sql

USE jimureport;

SET NAMES utf8mb4;

-- 报表主表（数据报表分类 984272091947253760）
INSERT INTO `jimu_report` (
  `id`, `code`, `name`, `note`, `status`, `type`, `json_str`,
  `api_url`, `thumb`, `create_by`, `create_time`, `update_by`, `update_time`,
  `del_flag`, `api_method`, `api_code`, `template`, `view_count`, `css_str`, `js_str`, `py_str`,
  `tenant_id`, `update_count`, `submit_form`, `is_multi_sheet`
) VALUES (
  'htma_profit_report_01',
  'htma_profit_001',
  '好特卖销售明细',
  '好特卖超级仓-毛利表数据绑定',
  NULL,
  '984272091947253760',
  '{"loopBlockList":[],"printConfig":{"paper":"A4","width":210,"height":297,"definition":1,"isBackend":false,"marginX":10,"marginY":10,"layout":"portrait"},"hidden":{"rows":[],"cols":[]},"dbexps":[],"dicts":[],"freeze":"A1","dataRectWidth":600,"autofilter":{},"validations":[],"cols":{"0":{"width":90},"1":{"width":80},"2":{"width":100},"3":{"width":100},"4":{"width":80},"5":{"width":100},"len":100},"area":{"sri":1,"sci":0,"eri":1,"eci":5,"width":100,"height":25},"pyGroupEngine":false,"excel_config_id":"htma_profit_report_01","hiddenCells":[],"zonedEditionList":[],"rows":{"0":{"cells":{"0":{"text":"日期"},"1":{"text":"品类"},"2":{"text":"总销售额"},"3":{"text":"总毛利"},"4":{"text":"毛利率"},"5":{"text":"门店"},"height":25}},"1":{"cells":{"0":{"text":"#{htma_profit.data_date}"},"1":{"text":"#{htma_profit.category}"},"2":{"text":"#{htma_profit.total_sale}"},"3":{"text":"#{htma_profit.total_profit}"},"4":{"text":"#{htma_profit.profit_rate}"},"5":{"text":"#{htma_profit.store_id}"}},"height":25},"len":200},"rpbar":{"show":true,"pageSize":"","btnList":[]}}',
  NULL,
  NULL,
  'admin',
  NOW(),
  'admin',
  NOW(),
  0,
  NULL,
  NULL,
  1,
  0,
  NULL,
  NULL,
  NULL,
  NULL,
  0,
  0,
  NULL
) ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `json_str` = VALUES(`json_str`),
  `update_by` = VALUES(`update_by`),
  `update_time` = VALUES(`update_time`);

-- 数据集：htma_profit，指向好特卖数据源
INSERT INTO `jimu_report_db` (
  `id`, `jimu_report_id`, `create_by`, `create_time`, `update_by`, `update_time`,
  `db_code`, `db_ch_name`, `db_type`, `db_dyn_sql`, `db_key`, `is_list`, `is_page`,
  `db_source`, `db_source_type`
) VALUES (
  'htma_profit_db_01',
  'htma_profit_report_01',
  'admin',
  NOW(),
  NULL,
  NULL,
  'htma_profit',
  '好特卖毛利汇总',
  '0',
  'SELECT data_date, category, total_sale, total_profit, profit_rate, store_id FROM t_htma_profit ORDER BY data_date, category',
  'htma_report_001',
  '1',
  '0',
  'htma_report_001',
  'MYSQL'
) ON DUPLICATE KEY UPDATE
  `jimu_report_id` = VALUES(`jimu_report_id`),
  `db_dyn_sql` = VALUES(`db_dyn_sql`),
  `db_key` = VALUES(`db_key`),
  `db_source` = VALUES(`db_source`);

-- 数据集字段（用于设计器展示）
INSERT INTO `jimu_report_db_field` (`id`, `create_by`, `create_time`, `jimu_report_db_id`, `field_name`, `field_text`, `order_num`) VALUES
('htma_f1', 'admin', NOW(), 'htma_profit_db_01', 'data_date', '日期', 1),
('htma_f2', 'admin', NOW(), 'htma_profit_db_01', 'category', '品类', 2),
('htma_f3', 'admin', NOW(), 'htma_profit_db_01', 'total_sale', '总销售额', 3),
('htma_f4', 'admin', NOW(), 'htma_profit_db_01', 'total_profit', '总毛利', 4),
('htma_f5', 'admin', NOW(), 'htma_profit_db_01', 'profit_rate', '毛利率', 5),
('htma_f6', 'admin', NOW(), 'htma_profit_db_01', 'store_id', '门店', 6)
ON DUPLICATE KEY UPDATE `field_text` = VALUES(`field_text`), `order_num` = VALUES(`order_num`);

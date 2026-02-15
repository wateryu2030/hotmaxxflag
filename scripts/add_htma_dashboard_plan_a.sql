-- =====================================================
-- 方案A：好特卖沈阳超级仓运营看板 - 一键部署
-- 包含：数据源、数据集、BI大屏（KPI+品类+趋势+库存预警）
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/add_htma_dashboard_plan_a.sql
-- =====================================================

USE jimureport;

SET NAMES utf8mb4;

-- 1. 确保好特卖数据源存在（仪表盘用 htma_drag_001）
INSERT IGNORE INTO `jimu_report_data_source` (
  `id`, `name`, `report_id`, `code`, `remark`,
  `db_type`, `db_driver`, `db_url`, `db_username`, `db_password`,
  `create_by`, `create_time`, `update_by`, `update_time`, `connect_times`, `tenant_id`, `type`
) VALUES
('htma_drag_001', '好特卖数据', NULL, 'htma_dashboard', '好特卖超级仓看板-销售/库存/毛利',
 'MYSQL5.7', 'com.mysql.cj.jdbc.Driver',
 'jdbc:mysql://127.0.0.1:3306/htma_dashboard?characterEncoding=UTF-8&useUnicode=true&useSSL=false&tinyInt1isBit=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai',
 'root', '62102218',
 'admin', NOW(), 'admin', NOW(), 0, '1', 'drag');

-- 2. 创建 BI 大屏主表
-- type 984302961118724096 = 图形报表(BI大屏)
SET @DASH_ID = 'htma_dash_shenyang_001';

INSERT INTO `jimu_report` (
  `id`, `code`, `name`, `note`, `status`, `type`, `json_str`,
  `api_url`, `thumb`, `create_by`, `create_time`, `update_by`, `update_time`,
  `del_flag`, `api_method`, `api_code`, `template`, `view_count`, `css_str`, `js_str`, `py_str`,
  `tenant_id`, `update_count`, `submit_form`, `is_multi_sheet`
) VALUES (
  @DASH_ID,
  'htma_shenyang_001',
  '好特卖沈阳超级仓运营看板',
  '方案A：经营总览+品类分析+销售趋势+库存预警',
  NULL,
  '984302961118724096',
  '{"loopBlockList":[],"chartList":[]}',
  NULL, NULL, 'admin', NOW(), 'admin', NOW(),
  0, NULL, NULL, 1, 0, NULL, NULL, NULL,
  '1', 0, NULL, NULL
) ON DUPLICATE KEY UPDATE
  `name` = VALUES(`name`),
  `note` = VALUES(`note`),
  `update_by` = VALUES(`update_by`),
  `update_time` = VALUES(`update_time`);

-- 3. 删除旧数据集（若存在）
DELETE FROM jimu_report_db_field WHERE jimu_report_db_id IN (
  'htma_db_kpi_sale','htma_db_kpi_profit','htma_db_kpi_rate','htma_db_kpi_stock',
  'htma_db_cat_pie','htma_db_daily_trend','htma_db_inv_alert'
);
DELETE FROM jimu_report_db_param WHERE jimu_report_head_id IN (
  'htma_db_kpi_sale','htma_db_kpi_profit','htma_db_kpi_rate','htma_db_cat_pie','htma_db_daily_trend','htma_db_inv_alert'
);
DELETE FROM jimu_report_db WHERE jimu_report_id = @DASH_ID;

-- 4. 新建数据集（使用近30天默认区间，无需参数）
-- 4.1 总销售额
INSERT INTO jimu_report_db (id, jimu_report_id, create_by, create_time, db_code, db_ch_name, db_type, db_dyn_sql, db_key, is_list, is_page, db_source, db_source_type) VALUES
('htma_db_kpi_sale', @DASH_ID, 'admin', NOW(), 'htma_kpi_sale', '总销售额', '0',
 'SELECT COALESCE(SUM(total_sale), 0) AS total_sale_amount FROM t_htma_profit WHERE store_id = ''沈阳超级仓'' AND data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 30 DAY) AND CURDATE()',
 'htma_drag_001', '0', '0', 'htma_drag_001', 'MYSQL');

-- 4.2 总毛利
INSERT INTO jimu_report_db (id, jimu_report_id, create_by, create_time, db_code, db_ch_name, db_type, db_dyn_sql, db_key, is_list, is_page, db_source, db_source_type) VALUES
('htma_db_kpi_profit', @DASH_ID, 'admin', NOW(), 'htma_kpi_profit', '总毛利', '0',
 'SELECT COALESCE(SUM(total_profit), 0) AS total_gross_profit FROM t_htma_profit WHERE store_id = ''沈阳超级仓'' AND data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 30 DAY) AND CURDATE()',
 'htma_drag_001', '0', '0', 'htma_drag_001', 'MYSQL');

-- 4.3 平均毛利率
INSERT INTO jimu_report_db (id, jimu_report_id, create_by, create_time, db_code, db_ch_name, db_type, db_dyn_sql, db_key, is_list, is_page, db_source, db_source_type) VALUES
('htma_db_kpi_rate', @DASH_ID, 'admin', NOW(), 'htma_kpi_rate', '平均毛利率', '0',
 'SELECT CASE WHEN SUM(total_sale) > 0 THEN ROUND(SUM(total_profit) / SUM(total_sale) * 100, 2) ELSE 0 END AS avg_profit_rate_pct FROM t_htma_profit WHERE store_id = ''沈阳超级仓'' AND data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 30 DAY) AND CURDATE()',
 'htma_drag_001', '0', '0', 'htma_drag_001', 'MYSQL');

-- 4.4 库存总额
INSERT INTO jimu_report_db (id, jimu_report_id, create_by, create_time, db_code, db_ch_name, db_type, db_dyn_sql, db_key, is_list, is_page, db_source, db_source_type) VALUES
('htma_db_kpi_stock', @DASH_ID, 'admin', NOW(), 'htma_kpi_stock', '库存总额', '0',
 'SELECT COALESCE(SUM(stock_amount), 0) AS total_stock_amount FROM t_htma_stock WHERE store_id = ''沈阳超级仓'' AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = ''沈阳超级仓'')',
 'htma_drag_001', '0', '0', 'htma_drag_001', 'MYSQL');

-- 4.5 品类销售额占比（饼图 Top5+其他）
INSERT INTO jimu_report_db (id, jimu_report_id, create_by, create_time, db_code, db_ch_name, db_type, db_dyn_sql, db_key, is_list, is_page, db_source, db_source_type) VALUES
('htma_db_cat_pie', @DASH_ID, 'admin', NOW(), 'htma_cat_pie', '品类销售额占比', '0',
 'WITH cs AS (SELECT COALESCE(category, ''未分类'') AS category, SUM(sale_amount) AS sale_amount FROM t_htma_sale WHERE store_id = ''沈阳超级仓'' AND data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 30 DAY) AND CURDATE() GROUP BY category),
 ranked AS (SELECT category, sale_amount, ROW_NUMBER() OVER (ORDER BY sale_amount DESC) AS rn FROM cs)
SELECT CASE WHEN rn <= 5 THEN category ELSE ''其他'' END AS category, SUM(sale_amount) AS sale_amount FROM ranked GROUP BY CASE WHEN rn <= 5 THEN category ELSE ''其他'' END ORDER BY sale_amount DESC',
 'htma_drag_001', '0', '0', 'htma_drag_001', 'MYSQL');

-- 4.6 日销售额趋势（柱状图）
INSERT INTO jimu_report_db (id, jimu_report_id, create_by, create_time, db_code, db_ch_name, db_type, db_dyn_sql, db_key, is_list, is_page, db_source, db_source_type) VALUES
('htma_db_daily_trend', @DASH_ID, 'admin', NOW(), 'htma_daily_trend', '日销售额趋势', '0',
 'SELECT data_date AS x_date, SUM(total_sale) AS daily_amount FROM t_htma_profit WHERE store_id = ''沈阳超级仓'' AND data_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 30 DAY) AND CURDATE() GROUP BY data_date ORDER BY data_date',
 'htma_drag_001', '0', '0', 'htma_drag_001', 'MYSQL');

-- 4.7 库存预警汇总
INSERT INTO jimu_report_db (id, jimu_report_id, create_by, create_time, db_code, db_ch_name, db_type, db_dyn_sql, db_key, is_list, is_page, db_source, db_source_type) VALUES
('htma_db_inv_alert', @DASH_ID, 'admin', NOW(), 'htma_inv_alert', '库存预警', '0',
 'SELECT COUNT(DISTINCT sku_code) AS alert_sku_count FROM t_htma_stock WHERE store_id = ''沈阳超级仓'' AND data_date = (SELECT MAX(data_date) FROM t_htma_stock WHERE store_id = ''沈阳超级仓'') AND stock_qty < 50 AND stock_qty >= 0',
 'htma_drag_001', '0', '0', 'htma_drag_001', 'MYSQL');

-- 5. 数据集字段（供设计器识别）
INSERT INTO jimu_report_db_field (id, create_by, create_time, jimu_report_db_id, field_name, field_text, order_num) VALUES
('htma_f_sale1', 'admin', NOW(), 'htma_db_kpi_sale', 'total_sale_amount', '总销售额', 1),
('htma_f_profit1', 'admin', NOW(), 'htma_db_kpi_profit', 'total_gross_profit', '总毛利', 1),
('htma_f_rate1', 'admin', NOW(), 'htma_db_kpi_rate', 'avg_profit_rate_pct', '平均毛利率%', 1),
('htma_f_stock1', 'admin', NOW(), 'htma_db_kpi_stock', 'total_stock_amount', '库存总额', 1),
('htma_f_pie1', 'admin', NOW(), 'htma_db_cat_pie', 'category', '品类', 1),
('htma_f_pie2', 'admin', NOW(), 'htma_db_cat_pie', 'sale_amount', '销售额', 2),
('htma_f_trend1', 'admin', NOW(), 'htma_db_daily_trend', 'x_date', '日期', 1),
('htma_f_trend2', 'admin', NOW(), 'htma_db_daily_trend', 'daily_amount', '日销售额', 2),
('htma_f_alert1', 'admin', NOW(), 'htma_db_inv_alert', 'alert_sku_count', '预警SKU数', 1)
ON DUPLICATE KEY UPDATE field_text = VALUES(field_text), order_num = VALUES(order_num);

-- 6. 更新大屏 json_str：添加 chartList 与基础布局
-- 含 rows/cols/area 等，避免 jmsheet 报 TypeError: Cannot convert undefined or null to object
-- 数字卡片(row,col): 总销售额(1,1), 总毛利(1,3), 毛利率(1,5), 库存(1,7)
-- 饼图(2,1), 趋势图(2,5)
-- 预警数字(3,1)
UPDATE jimu_report SET json_str = '{
  "loopBlockList": [],
  "rows": {"0": {"cells": {"0": {"text": "好特卖沈阳超级仓运营看板"}}, "height": 40}},
  "cols": {"0": {"width": 100}, "len": 100},
  "area": {"sri": 0, "sci": 0, "eri": 0, "eci": 0, "width": 100, "height": 100},
  "styles": {},
  "merges": [],
  "printConfig": {"paper": "A4", "width": 210, "height": 297, "definition": 1, "isBackend": false, "marginX": 10, "marginY": 10, "layout": "portrait"},
  "chartList": [
    {"row":1,"col":1,"colspan":2,"rowspan":2,"width":"180","height":"80","extData":{"dbCode":"htma_kpi_sale","dataId":"htma_db_kpi_sale","dataType":"sql","chartType":"numberCard","axisY":"total_sale_amount","title":"总销售额"},"config":"{}"},
    {"row":1,"col":3,"colspan":2,"rowspan":2,"width":"180","height":"80","extData":{"dbCode":"htma_kpi_profit","dataId":"htma_db_kpi_profit","dataType":"sql","chartType":"numberCard","axisY":"total_gross_profit","title":"总毛利"},"config":"{}"},
    {"row":1,"col":5,"colspan":2,"rowspan":2,"width":"180","height":"80","extData":{"dbCode":"htma_kpi_rate","dataId":"htma_db_kpi_rate","dataType":"sql","chartType":"numberCard","axisY":"avg_profit_rate_pct","title":"平均毛利率%"},"config":"{}"},
    {"row":1,"col":7,"colspan":2,"rowspan":2,"width":"180","height":"80","extData":{"dbCode":"htma_kpi_stock","dataId":"htma_db_kpi_stock","dataType":"sql","chartType":"numberCard","axisY":"total_stock_amount","title":"库存总额"},"config":"{}"},
    {"row":3,"col":1,"colspan":4,"rowspan":8,"width":"400","height":"300","extData":{"dbCode":"htma_cat_pie","dataId":"htma_db_cat_pie","dataType":"sql","chartType":"pie","axisX":"category","axisY":"sale_amount","title":"品类销售额占比"},"config":"{}"},
    {"row":3,"col":5,"colspan":4,"rowspan":8,"width":"400","height":"300","extData":{"dbCode":"htma_daily_trend","dataId":"htma_db_daily_trend","dataType":"sql","chartType":"bar","axisX":"x_date","axisY":"daily_amount","title":"日销售额趋势"},"config":"{}"},
    {"row":11,"col":1,"colspan":2,"rowspan":2,"width":"180","height":"80","extData":{"dbCode":"htma_inv_alert","dataId":"htma_db_inv_alert","dataType":"sql","chartType":"numberCard","axisY":"alert_sku_count","title":"低库存预警SKU数"},"config":"{}"}
  ]
}' WHERE id = @DASH_ID;

SELECT 'Done. 好特卖沈阳超级仓运营看板已创建。访问: http://127.0.0.1:8085/jmreport/view/htma_dash_shenyang_001' AS msg;

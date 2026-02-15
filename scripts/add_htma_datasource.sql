-- 在 JimuReport 的 jimureport 库中新增「好特卖数据」数据源，报表和仪表盘均可使用
-- 执行: mysql -h 127.0.0.1 -u root -p62102218 jimureport < scripts/add_htma_datasource.sql

USE jimureport;

INSERT INTO `jimu_report_data_source` (
  `id`, `name`, `report_id`, `code`, `remark`,
  `db_type`, `db_driver`, `db_url`, `db_username`, `db_password`,
  `create_by`, `create_time`, `update_by`, `update_time`, `connect_times`, `tenant_id`, `type`
) VALUES
-- 报表设计器用
('htma_report_001', '好特卖数据', NULL, 'htma_dashboard', '好特卖超级仓看板-销售/库存/毛利',
 'MYSQL5.7', 'com.mysql.cj.jdbc.Driver',
 'jdbc:mysql://127.0.0.1:3306/htma_dashboard?characterEncoding=UTF-8&useUnicode=true&useSSL=false&tinyInt1isBit=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai',
 'root', '62102218',
 'admin', NOW(), 'admin', NOW(), 0, NULL, 'report'),
-- 仪表盘(BI)用
('htma_drag_001', '好特卖数据', NULL, 'htma_dashboard', '好特卖超级仓看板-销售/库存/毛利',
 'MYSQL5.7', 'com.mysql.cj.jdbc.Driver',
 'jdbc:mysql://127.0.0.1:3306/htma_dashboard?characterEncoding=UTF-8&useUnicode=true&useSSL=false&tinyInt1isBit=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai',
 'root', '62102218',
 'admin', NOW(), 'admin', NOW(), 0, '1', 'drag');

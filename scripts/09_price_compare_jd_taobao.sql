-- =====================================================
-- 货盘比价结果表（京东+淘宝双平台，实体化保存供决策参考）
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/09_price_compare_jd_taobao.sql
-- =====================================================

USE htma_dashboard;

-- 扩展 t_htma_price_compare：增加京东/淘宝分平台价格、raw_name、spec、barcode
-- 若列已存在会报错，可忽略
ALTER TABLE t_htma_price_compare ADD COLUMN raw_name VARCHAR(128) DEFAULT NULL COMMENT '原始品名' AFTER std_name;
ALTER TABLE t_htma_price_compare ADD COLUMN spec VARCHAR(64) DEFAULT NULL COMMENT '规格' AFTER raw_name;
ALTER TABLE t_htma_price_compare ADD COLUMN barcode VARCHAR(64) DEFAULT NULL COMMENT '条码' AFTER spec;
ALTER TABLE t_htma_price_compare ADD COLUMN jd_min_price DECIMAL(12,2) DEFAULT NULL COMMENT '京东最低价' AFTER unit_price;
ALTER TABLE t_htma_price_compare ADD COLUMN jd_platform VARCHAR(64) DEFAULT NULL COMMENT '京东数据来源' AFTER jd_min_price;
ALTER TABLE t_htma_price_compare ADD COLUMN taobao_min_price DECIMAL(12,2) DEFAULT NULL COMMENT '淘宝最低价' AFTER jd_platform;
ALTER TABLE t_htma_price_compare ADD COLUMN taobao_platform VARCHAR(64) DEFAULT NULL COMMENT '淘宝数据来源' AFTER taobao_min_price;

-- 消费洞察查询性能优化：为 t_htma_sale 添加复合索引
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/21_add_consumer_insight_indexes.sql
-- 若索引已存在则跳过

USE htma_dashboard;

-- (store_id, data_date) 为消费洞察最常用筛选组合
SET @idx1 = (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 't_htma_sale' AND INDEX_NAME = 'idx_store_date');
SET @sql1 = IF(@idx1 = 0, 'CREATE INDEX idx_store_date ON t_htma_sale (store_id, data_date)', 'SELECT ''idx_store_date 已存在'' AS msg');
PREPARE stmt1 FROM @sql1;
EXECUTE stmt1;
DEALLOCATE PREPARE stmt1;

-- =====================================================
-- 货盘价格对比分析 - 结果存储表
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/07_create_price_compare.sql
-- =====================================================

USE htma_dashboard;

-- 价格对比结果表（可选，用于缓存/历史）
CREATE TABLE IF NOT EXISTS t_htma_price_compare (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  run_at        DATETIME        NOT NULL COMMENT '分析执行时间',
  store_id      VARCHAR(32)     DEFAULT '沈阳超级仓',
  days          INT             DEFAULT 30 COMMENT '分析周期天数',
  sku_code      VARCHAR(64)     NOT NULL,
  std_name      VARCHAR(128)    DEFAULT NULL COMMENT '标准化商品名',
  category      VARCHAR(64)     DEFAULT NULL,
  unit_price    DECIMAL(12,2)   DEFAULT NULL COMMENT '好特卖单价',
  competitor_min DECIMAL(12,2)  DEFAULT NULL COMMENT '竞品最低价',
  advantage_pct DECIMAL(6,2)    DEFAULT NULL COMMENT '价格优势率%',
  tier          VARCHAR(32)    DEFAULT NULL COMMENT '高优势款/中等优势款/无优势款/价格劣势款/独家款',
  platform      VARCHAR(64)     DEFAULT NULL COMMENT '竞品来源平台',
  created_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,
  KEY idx_run (run_at),
  KEY idx_sku (sku_code),
  KEY idx_tier (tier)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='货盘价格对比结果';

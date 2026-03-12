-- =====================================================
-- 百度优选 Skill 比价结果表（跨平台 taobao/jd/vip 等）
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/23_create_t_price_compare.sql
-- =====================================================

USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_price_compare (
  id INT AUTO_INCREMENT PRIMARY KEY,
  sku_code VARCHAR(64) NOT NULL COMMENT '商品货号',
  product_name VARCHAR(256) DEFAULT NULL COMMENT '商品名称',
  brand VARCHAR(128) DEFAULT NULL COMMENT '品牌',
  platform VARCHAR(32) NOT NULL COMMENT '平台（taobao/jd/vip等）',
  price DECIMAL(12,2) NOT NULL COMMENT '当前价格',
  original_price DECIMAL(12,2) DEFAULT NULL COMMENT '原价/划线价',
  promotion_info VARCHAR(500) DEFAULT NULL COMMENT '促销信息',
  price_trend TEXT DEFAULT NULL COMMENT '价格走势JSON',
  good_rate DECIMAL(5,2) DEFAULT NULL COMMENT '用户好评率',
  capture_date DATETIME NOT NULL COMMENT '抓取时间',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_sku (sku_code),
  INDEX idx_product (product_name(64)),
  INDEX idx_capture (capture_date),
  INDEX idx_sku_platform (sku_code, platform)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='百度优选Skill跨平台比价结果';

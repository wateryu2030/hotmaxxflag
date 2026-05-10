-- 微信订阅消息配置 + daily_category_stats 常用索引（按需执行）
-- 推荐用 Python 读 .env 自动执行：python3 scripts/apply_32_wechat_subscription.py
USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_htma_wechat_subscription (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id BIGINT UNSIGNED NOT NULL COMMENT 't_htma_wechat_user.id',
  template_id VARCHAR(64) NOT NULL COMMENT '订阅消息模板 ID',
  openid VARCHAR(64) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_tpl (user_id, template_id),
  KEY idx_openid_active (openid, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='小程序订阅消息';

-- 若不存在则创建（已存在会报错可忽略）
-- ALTER TABLE daily_category_stats ADD INDEX idx_store_date (store_id, data_date);
-- ALTER TABLE daily_category_stats ADD INDEX idx_large_date (category_large_code, data_date);
-- ALTER TABLE daily_category_stats ADD INDEX idx_data_date (data_date);

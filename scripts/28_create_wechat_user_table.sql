-- 微信小程序用户（独立于飞书登录；与项目 PyMySQL 一致，非 ORM）
-- mysql ... < scripts/28_create_wechat_user_table.sql

USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_htma_wechat_user (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  openid VARCHAR(64) NOT NULL COMMENT '微信 openid',
  unionid VARCHAR(64) DEFAULT NULL COMMENT '微信 unionid',
  phone VARCHAR(32) DEFAULT NULL COMMENT '绑定手机号',
  nickname VARCHAR(128) DEFAULT NULL,
  avatar_url VARCHAR(512) DEFAULT NULL,
  feishu_open_id VARCHAR(128) DEFAULT NULL COMMENT '可选绑定飞书 open_id',
  role VARCHAR(32) NOT NULL DEFAULT 'operator' COMMENT 'store_manager|region_manager|operator',
  store_id VARCHAR(32) DEFAULT NULL COMMENT 'NULL 表示不按单店过滤（全店/待分配）',
  session_key VARCHAR(256) DEFAULT NULL COMMENT 'jscode2session 的 session_key（Base64 串），用于旧版手机号解密',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_wechat_openid (openid),
  UNIQUE KEY uk_wechat_phone (phone),
  KEY idx_store_role (store_id, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信小程序用户';

-- Phase 2：规则引擎预警事件 + AI 经营快报（按需执行）
USE htma_dashboard;

CREATE TABLE IF NOT EXISTS alert_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type VARCHAR(64) NOT NULL COMMENT '规则类型，如 low_margin_large',
  level VARCHAR(16) NOT NULL DEFAULT 'warning' COMMENT 'critical | warning | info',
  title VARCHAR(255) NOT NULL,
  summary TEXT NULL COMMENT '列表展示摘要',
  payload_json JSON NULL COMMENT '扩展字段：大类编码、指标等',
  store_id VARCHAR(64) NOT NULL DEFAULT '' COMMENT '门店维度；空串表示全店汇总任务写入',
  dedupe_key VARCHAR(192) NOT NULL DEFAULT '' COMMENT '同日去重键',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  acked_at DATETIME NULL,
  ack_user_id BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  KEY idx_store_open (store_id, created_at),
  KEY idx_acked (acked_at),
  KEY idx_dedupe_created (dedupe_key, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='规则引擎产出预警';

CREATE TABLE IF NOT EXISTS daily_ai_reports (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  report_date DATE NOT NULL,
  store_id VARCHAR(64) NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  meta_json JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_store_report_date (store_id, report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日 AI 经营快报';

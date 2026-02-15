-- 营销报告发送记录表，供 AI 分析界面展示及后续分析总结
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/06_create_report_log.sql

USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_htma_report_log (
  id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  report_date   DATE            NOT NULL COMMENT '报告日期',
  report_time   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '生成时间',
  store_id      VARCHAR(32)     DEFAULT '沈阳超级仓' COMMENT '门店',
  report_content TEXT           NOT NULL COMMENT '报告全文',
  feishu_at_user_id VARCHAR(64) DEFAULT NULL COMMENT '飞书@接收人 open_id',
  feishu_at_user_name VARCHAR(32) DEFAULT NULL COMMENT '飞书@接收人姓名',
  send_status   TINYINT         DEFAULT 1 COMMENT '发送状态: 0失败 1成功',
  send_error    VARCHAR(512)    DEFAULT NULL COMMENT '发送失败原因',
  created_at    DATETIME        DEFAULT CURRENT_TIMESTAMP,
  KEY idx_report_date (report_date),
  KEY idx_created (created_at),
  KEY idx_store (store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='好特卖-营销报告发送记录';

SELECT 'Done. t_htma_report_log 已创建' AS msg;

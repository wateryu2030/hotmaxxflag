-- 收益评估结果表增加自定义时间段字段
USE htma_dashboard;

ALTER TABLE t_profit_share_result
  ADD COLUMN period_start DATE DEFAULT NULL COMMENT '计算周期起' AFTER calc_month,
  ADD COLUMN period_end DATE DEFAULT NULL COMMENT '计算周期止' AFTER period_start;

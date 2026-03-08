-- -----------------------------------------------------
-- 人力成本分析表：由 t_htma_labor_cost 汇总生成，用于月度比对与分析
-- 数据分级：原始明细 -> t_htma_labor_cost；汇总比对 -> 本表
-- -----------------------------------------------------
USE htma_dashboard;

CREATE TABLE IF NOT EXISTS t_htma_labor_cost_analysis (
  report_month          VARCHAR(7)   NOT NULL PRIMARY KEY COMMENT '报表月份 YYYY-MM',
  leader_count          INT          NOT NULL DEFAULT 0 COMMENT '组长/职能岗位数',
  leader_total_cost     DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '组长费用总额',
  fulltime_count        INT          NOT NULL DEFAULT 0 COMMENT '组员/全职岗位数',
  fulltime_total_cost   DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '组员公司成本合计',
  fulltime_total_hours  DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '组员总工时',
  total_labor_cost      DECIMAL(14,2) NOT NULL DEFAULT 0 COMMENT '人力成本合计',
  prev_month_total      DECIMAL(14,2) DEFAULT NULL COMMENT '上月人力成本合计(用于环比)',
  mom_pct               DECIMAL(8,2)  DEFAULT NULL COMMENT '环比%',
  created_at            DATETIME     DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人力成本月度汇总与比对';

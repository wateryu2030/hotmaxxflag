-- -----------------------------------------------------
-- 人力成本明细表：按报表月份+岗位类型+岗位+姓名到人，支持组长/组员/兼职/小时工/保洁/管理岗
-- position_type: leader=组长, fulltime=组员, parttime=兼职, hourly=小时工, cleaner=保洁, management=管理岗
-- 唯一键含 person_name，同一岗位多人不重复
-- -----------------------------------------------------
USE htma_dashboard;

DROP TABLE IF EXISTS t_htma_labor_cost;

CREATE TABLE t_htma_labor_cost (
  id                 BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
  report_month       VARCHAR(7)       NOT NULL COMMENT '报表月份 YYYY-MM',
  position_type      VARCHAR(20)      NOT NULL COMMENT 'leader/fulltime/parttime/hourly/cleaner/management',
  position_name      VARCHAR(64)      NOT NULL COMMENT '岗位/分类名称',
  person_name        VARCHAR(64)      NOT NULL DEFAULT '' COMMENT '姓名',
  total_salary       DECIMAL(14, 2)   DEFAULT NULL COMMENT '合计薪资',
  pre_tax_pay        DECIMAL(14, 2)   DEFAULT NULL COMMENT '税前应发',
  actual_salary      DECIMAL(14, 2)   DEFAULT NULL COMMENT '实际薪资合计',
  luxury_bonus       DECIMAL(14, 2)   DEFAULT NULL COMMENT '奢品奖金(组长)',
  work_hours         DECIMAL(12, 2)   DEFAULT NULL COMMENT '总工时(全职)',
  base_salary        DECIMAL(14, 2)   DEFAULT NULL COMMENT '基本工资(全职)',
  performance        DECIMAL(14, 2)   DEFAULT NULL COMMENT '绩效(全职)',
  position_allowance  DECIMAL(14, 2)   DEFAULT NULL COMMENT '岗位补贴(全职)',
  luxury_amount      DECIMAL(14, 2)   DEFAULT NULL COMMENT '奢品(全职)',
  actual_income      DECIMAL(14, 2)   DEFAULT NULL COMMENT '实得收入',
  company_cost       DECIMAL(14, 2)   DEFAULT NULL COMMENT '公司实际成本',
  total_cost         DECIMAL(14, 2)   DEFAULT NULL COMMENT '费用总额/开票金额/总成本',
  supplier_name      VARCHAR(64)      NOT NULL DEFAULT '' COMMENT '供应商(斗米/中锐/快聘/保洁等)',
  store_id           VARCHAR(32)      DEFAULT '沈阳超级仓' COMMENT '门店ID',
  -- 兼职/小时工明细扩展（店铺名、城市、入职/离职日期、工时、时薪、发薪、服务费、税费等）
  store_name         VARCHAR(64)      DEFAULT NULL COMMENT '店铺名',
  city               VARCHAR(32)      DEFAULT NULL COMMENT '城市',
  join_date          VARCHAR(32)      DEFAULT NULL COMMENT '入职日期',
  leave_date         VARCHAR(32)      DEFAULT NULL COMMENT '离职日期',
  normal_hours       DECIMAL(12, 2)   DEFAULT NULL COMMENT '普通工时',
  triple_pay_hours   DECIMAL(12, 2)   DEFAULT NULL COMMENT '三薪工时',
  hourly_rate        DECIMAL(10, 2)   DEFAULT NULL COMMENT '时薪',
  pay_amount         DECIMAL(14, 2)   DEFAULT NULL COMMENT '发薪金额',
  service_fee_unit   DECIMAL(10, 2)   DEFAULT NULL COMMENT '服务费单价',
  service_fee_total  DECIMAL(14, 2)   DEFAULT NULL COMMENT '服务费总计',
  tax                DECIMAL(14, 2)   DEFAULT NULL COMMENT '税费',
  cost_include       VARCHAR(32)      DEFAULT NULL COMMENT '成本计入(兼职/小时工)',
  department         VARCHAR(64)      DEFAULT NULL COMMENT '用人部门(中锐/快聘等)',
  created_at         DATETIME         DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME         DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_month_type_position (report_month, position_type, position_name, person_name(64), supplier_name(64), store_id),
  KEY idx_report_month (report_month),
  KEY idx_position_type (position_type),
  KEY idx_store (store_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='人力成本到人明细-组长/组员/兼职/小时工/保洁/管理岗';

-- =====================================================
-- 收益评估（加盟商分账）模块 - 建表脚本
-- 数据库: htma_dashboard
-- =====================================================

USE htma_dashboard;

-- -----------------------------------------------------
-- 1. 分账规则配置表
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS t_profit_share_rule (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stage_name VARCHAR(50) NOT NULL COMMENT '阶段名称，如“前两年”、“两年后”',
    share_rate_merchant DECIMAL(5,2) NOT NULL COMMENT '加盟商分成比例（%）',
    share_rate_platform DECIMAL(5,2) NOT NULL COMMENT '平台分成比例（%）',
    effective_start DATE NOT NULL COMMENT '生效开始日期',
    effective_end DATE DEFAULT NULL COMMENT '生效结束日期，NULL表示永久',
    is_active TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否启用（同一时间只能一条启用）',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分账规则配置';

-- -----------------------------------------------------
-- 2. 品类排除配置表
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS t_profit_share_exclude_category (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_large_code VARCHAR(20) DEFAULT NULL COMMENT '大类编码，为空表示所有大类',
    category_large_name VARCHAR(100) DEFAULT NULL COMMENT '大类名称（冗余）',
    category_mid_code VARCHAR(20) DEFAULT NULL COMMENT '中类编码，为空表示排除整个大类',
    category_mid_name VARCHAR(100) DEFAULT NULL COMMENT '中类名称（冗余）',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_large_mid (category_large_code, category_mid_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分账品类排除配置';

-- -----------------------------------------------------
-- 3. 分账计算结果表
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS t_profit_share_result (
    id INT AUTO_INCREMENT PRIMARY KEY,
    calc_month VARCHAR(7) NOT NULL COMMENT '计算月份，格式 YYYY-MM',
    total_sales DECIMAL(15,2) NOT NULL COMMENT '参与计算的总销售额（含税）',
    total_cost DECIMAL(15,2) NOT NULL COMMENT '参与计算的总销售成本（含税）',
    total_profit DECIMAL(15,2) NOT NULL COMMENT '总毛利额',
    share_rate_used DECIMAL(5,2) NOT NULL COMMENT '实际使用的加盟商分成比例（%）',
    merchant_settle_amount DECIMAL(15,2) NOT NULL COMMENT '加盟商结算金额',
    platform_amount DECIMAL(15,2) NOT NULL COMMENT '平台留存金额',
    rule_id INT NOT NULL COMMENT '使用的规则ID',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(50) DEFAULT NULL COMMENT '操作用户'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分账计算结果';

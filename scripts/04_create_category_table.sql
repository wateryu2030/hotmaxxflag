-- =====================================================
-- 品类主数据表：大类/中类/小类级联（与附表结构一致）
-- 编码规则：中类编码前2位=大类编码，小类编码前4位=中类编码
-- 执行: mysql -h 127.0.0.1 -u root -p htma_dashboard < scripts/04_create_category_table.sql
-- =====================================================

USE htma_dashboard;

-- 品类主数据表（附表结构：大类编、大类名称、中类编、中类名称、小类编、小类名称）
DROP TABLE IF EXISTS t_htma_category;

CREATE TABLE t_htma_category (
  id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  category_large_code VARCHAR(16)   NOT NULL COMMENT '大类编码(2位)',
  category_large     VARCHAR(64)   NOT NULL COMMENT '大类名称',
  category_mid_code  VARCHAR(16)   NOT NULL DEFAULT '' COMMENT '中类编码(4位,前2位=大类)',
  category_mid       VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '中类名称',
  category_small_code VARCHAR(16)  NOT NULL DEFAULT '' COMMENT '小类编码(6位,前4位=中类)',
  category_small     VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '小类名称',
  created_at         DATETIME      DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_codes (category_large_code, category_mid_code, category_small_code),
  KEY idx_large (category_large_code),
  KEY idx_mid (category_mid_code),
  KEY idx_small (category_small_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='品类主数据-大类中类小类级联';

SELECT 'Done. t_htma_category 已创建' AS msg;

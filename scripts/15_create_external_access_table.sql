-- 企业外飞书用户访问审批：企业外用户扫码后待超级管理员（余为军）审批通过方可访问
CREATE TABLE IF NOT EXISTS t_htma_external_access (
  id INT AUTO_INCREMENT PRIMARY KEY,
  open_id VARCHAR(64) NOT NULL COMMENT '飞书 open_id',
  name VARCHAR(128) DEFAULT NULL COMMENT '用户姓名',
  union_id VARCHAR(64) DEFAULT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending/approved/rejected',
  requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  decided_by_open_id VARCHAR(64) DEFAULT NULL COMMENT '审批人 open_id',
  decided_at DATETIME DEFAULT NULL,
  UNIQUE KEY uk_open_id (open_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='企业外用户访问审批';

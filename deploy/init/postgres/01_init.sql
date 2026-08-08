-- BirchAtlas PostgreSQL 初始化脚本
-- 创建核心业务表

-- 用户表
CREATE TABLE IF NOT EXISTS sys_user (
  id BIGSERIAL PRIMARY KEY,
  username VARCHAR(64) UNIQUE NOT NULL,
  password_hash VARCHAR(256) NOT NULL,
  real_name VARCHAR(64),
  email VARCHAR(128),
  phone VARCHAR(32),
  status SMALLINT DEFAULT 1,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 角色表
CREATE TABLE IF NOT EXISTS sys_role (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(64) UNIQUE NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 用户角色关联
CREATE TABLE IF NOT EXISTS sys_user_role (
  user_id BIGINT REFERENCES sys_user(id) ON DELETE CASCADE,
  role_id BIGINT REFERENCES sys_role(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, role_id)
);

-- 权限表
CREATE TABLE IF NOT EXISTS sys_permission (
  id BIGSERIAL PRIMARY KEY,
  role_id BIGINT REFERENCES sys_role(id) ON DELETE CASCADE,
  resource VARCHAR(128) NOT NULL,
  action VARCHAR(32) NOT NULL,
  UNIQUE(role_id, resource, action)
);

-- 审计日志
CREATE TABLE IF NOT EXISTS sys_audit_log (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT,
  action VARCHAR(64) NOT NULL,
  resource VARCHAR(128),
  detail JSONB,
  ip_address VARCHAR(64),
  user_agent TEXT,
  status SMALLINT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 设备表（沿用 AA-BBBBBBBB 规则）
CREATE TABLE IF NOT EXISTS device (
  id BIGSERIAL PRIMARY KEY,
  device_code VARCHAR(12) UNIQUE NOT NULL,
  device_type SMALLINT NOT NULL,
  name VARCHAR(64),
  status SMALLINT DEFAULT 0,
  fingerprint VARCHAR(128),
  cert_sn VARCHAR(64),
  project_id BIGINT,
  position JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 设备影子
CREATE TABLE IF NOT EXISTS device_shadow (
  device_id BIGINT PRIMARY KEY REFERENCES device(id) ON DELETE CASCADE,
  desired JSONB NOT NULL DEFAULT '{}',
  reported JSONB NOT NULL DEFAULT '{}',
  delta JSONB NOT NULL DEFAULT '{}',
  version BIGINT DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 项目表
CREATE TABLE IF NOT EXISTS project (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  description TEXT,
  owner_id BIGINT,
  status SMALLINT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 测点表
CREATE TABLE IF NOT EXISTS measure_point (
  id BIGSERIAL PRIMARY KEY,
  gateway_id BIGINT NOT NULL REFERENCES device(id),
  project_id BIGINT NOT NULL REFERENCES project(id),
  name VARCHAR(64),
  algo_id BIGINT,
  params JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 算法包表
CREATE TABLE IF NOT EXISTS algo_package (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(64) NOT NULL,
  version VARCHAR(32) NOT NULL,
  type VARCHAR(16),
  status SMALLINT DEFAULT 0,
  storage_path VARCHAR(256),
  signature TEXT,
  test_report JSONB,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(name, version)
);

-- 检测任务表
CREATE TABLE IF NOT EXISTS task (
  id BIGSERIAL PRIMARY KEY,
  task_type VARCHAR(32),
  target JSONB,
  status SMALLINT DEFAULT 0,
  payload JSONB,
  result JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 聚类任务表
CREATE TABLE IF NOT EXISTS cluster_job (
  id BIGSERIAL PRIMARY KEY,
  job_id VARCHAR(64) UNIQUE NOT NULL,
  algorithm VARCHAR(32) NOT NULL,
  params JSONB,
  status SMALLINT DEFAULT 0,
  created_by BIGINT,
  created_at TIMESTAMPTZ DEFAULT now(),
  finished_at TIMESTAMPTZ
);

-- 告警规则表
CREATE TABLE IF NOT EXISTS alert_rule (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(64) NOT NULL,
  rule_type VARCHAR(32),
  condition JSONB,
  severity SMALLINT DEFAULT 1,
  enabled BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 告警事件表
CREATE TABLE IF NOT EXISTS alert_event (
  id BIGSERIAL PRIMARY KEY,
  rule_id BIGINT REFERENCES alert_rule(id),
  event_type VARCHAR(32),
  severity SMALLINT DEFAULT 1,
  message TEXT,
  detail JSONB,
  status SMALLINT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_device_code ON device(device_code);
CREATE INDEX IF NOT EXISTS idx_device_status ON device(status);
CREATE INDEX IF NOT EXISTS idx_project_status ON project(status);
CREATE INDEX IF NOT EXISTS idx_measure_point_gateway ON measure_point(gateway_id);
CREATE INDEX IF NOT EXISTS idx_measure_point_project ON measure_point(project_id);
CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);
CREATE INDEX IF NOT EXISTS idx_task_type ON task(task_type);
CREATE INDEX IF NOT EXISTS idx_cluster_job_status ON cluster_job(status);
CREATE INDEX IF NOT EXISTS idx_alert_event_status ON alert_event(status);
CREATE INDEX IF NOT EXISTS idx_alert_event_severity ON alert_event(severity);

-- 初始数据：默认角色
INSERT INTO sys_role (name, description) VALUES
  ('admin', '系统管理员'),
  ('engineer', '工程师'),
  ('viewer', '查看者')
ON CONFLICT (name) DO NOTHING;
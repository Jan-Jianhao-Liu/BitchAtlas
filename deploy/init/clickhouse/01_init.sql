-- BirchAtlas ClickHouse 初始化脚本
-- 创建检测数据明细表和聚类结果表

-- 检测数据明细表（兼容 V1.0 字段）
CREATE TABLE IF NOT EXISTS detect_data (
  record_time DateTime64(3) CODEC(Delta, ZSTD),
  project_id UInt64,
  gateway_code String,
  dev_code String,
  measure_point_id UInt64,
  img_url String,
  factor Float64,
  high Float64,
  data_type UInt8,
  vals Array(Float64),
  outlier_flag UInt8 DEFAULT 0,
  outlier_indices Array(UInt32) DEFAULT [],
  quality_grade String DEFAULT 'A',
  source UInt8,
  algo_version String DEFAULT '',
  record_id String DEFAULT ''
) ENGINE = MergeTree
PARTITION BY toYYYYMM(record_time)
ORDER BY (project_id, record_time)
TTL record_time + INTERVAL 1 YEAR;

-- 聚类结果表
CREATE TABLE IF NOT EXISTS cluster_result (
  job_id String,
  cluster_id UInt32,
  point_id UInt64,
  features Array(Float64),
  label Int32,
  distance Float64 DEFAULT 0,
  created_at DateTime64(3)
) ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (job_id, cluster_id);

-- 聚类评估表
CREATE TABLE IF NOT EXISTS cluster_eval (
  job_id String,
  algorithm String,
  silhouette_score Float64,
  davies_bouldin Float64,
  calinski_harabasz Float64,
  n_clusters UInt32,
  n_points UInt64,
  params JSON,
  created_at DateTime64(3)
) ENGINE = ReplacingMergeTree(created_at)
ORDER BY (job_id, algorithm);

-- BIRCH CF 树存储表（用于云端合并）
CREATE TABLE IF NOT EXISTS cf_tree_data (
  gateway_code String,
  record_time DateTime64(3),
  cf_tree_id String,
  serialized_data String,
  num_points UInt64,
  num_clusters UInt32
) ENGINE = MergeTree
PARTITION BY toYYYYMM(record_time)
ORDER BY (gateway_code, record_time);

-- 异常检测记录表
CREATE TABLE IF NOT EXISTS anomaly_record (
  record_time DateTime64(3),
  gateway_code String,
  dev_code String,
  measure_point_id UInt64,
  data_type UInt8,
  value_index UInt32,
  value Float64,
  expected_mean Float64,
  expected_std Float64,
  z_score Float64,
  anomaly_type String,
  handled UInt8 DEFAULT 0
) ENGINE = MergeTree
PARTITION BY toYYYYMM(record_time)
ORDER BY (gateway_code, record_time)
TTL record_time + INTERVAL 6 MONTH;

-- 创建视图：设备统计
CREATE VIEW IF NOT EXISTS v_device_stats AS
SELECT
  project_id,
  gateway_code,
  count() as total_records,
  min(record_time) as first_record,
  max(record_time) as last_record
FROM detect_data
GROUP BY project_id, gateway_code;

-- 创建视图：质量汇总
CREATE VIEW IF NOT EXISTS v_quality_summary AS
SELECT
  project_id,
  quality_grade,
  count() as count,
  avg(factor) as avg_factor
FROM detect_data
WHERE quality_grade != ''
GROUP BY project_id, quality_grade;
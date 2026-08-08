"""
BirchAtlas - 边缘网关配置
=========================

定义网关运行所需的全部配置项，包括：
- MQTT 连接参数（host/port/账号密码）
- 网关与项目标识（gateway_code/project_id）
- 测点列表（measure_points）
- 聚类算法参数（radius_threshold/threshold_k 等）

提供两种加载方式：
1. GatewayConfig.from_env()  —— 从环境变量加载（适合容器化部署）
2. GatewayConfig.from_file() —— 从 JSON 文件加载（适合本地调试）

环境变量命名规范：全大写下划线分隔，例如 GATEWAY_CODE、MQTT_HOST。
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class ClusteringConfig:
    """
    BIRCH 聚类算法配置

    与 edge.clustering.BirchTree / OutlierDetector 的构造参数一一对应。
    """
    radius_threshold: float = 1.0          # 簇半径阈值 T（控制簇紧密度）
    max_children: int = 5                  # CF 树节点最大子节点数 B
    threshold_k: float = 3.0               # 离群判定 k·σ 倍数
    consecutive_limit: int = 3             # 连续离群触发告警的次数
    min_points_for_detection: int = 10     # 启用 CF 树检测前所需的最少数据点
    min_baseline_cf_points: int = 2        # CF 作为基线所需的最少点数


@dataclass
class MeasurePoint:
    """
    单个测点配置

    一个网关可挂载多个测点（如楼板的不同采样位置），每个测点独立维护
    一棵 BIRCH 树和离群检测器。
    """
    point_id: str                          # 测点编号，如 "MP-001"
    name: str = ""                         # 测点名称（便于人读）
    data_types: List[int] = field(default_factory=lambda: [1, 2, 3, 4])
    # data_types 对应钢筋间距检测的四类数据：
    #   1=底横筋 2=底纵筋 3=面横筋 4=面纵筋


@dataclass
class GatewayConfig:
    """
    边缘网关完整配置

    使用 dataclass 提供合理的默认值，可通过 from_env / from_file 覆盖。
    """
    # —— 网关标识 ——
    gateway_code: str = "GW-00000001"      # 网关唯一编号
    project_id: str = ""                   # 所属项目 ID

    # —— MQTT 连接 ——
    mqtt_host: str = "localhost"           # MQTT broker 地址
    mqtt_port: int = 1883                  # MQTT broker 端口
    username: str = ""                     # MQTT 用户名（可空）
    password: str = ""                     # MQTT 密码（可空）
    keepalive: int = 60                    # MQTT 心跳保持时长（秒）

    # —— 运行参数 ——
    heartbeat_interval: int = 30           # 业务心跳间隔（秒）

    # —— 业务配置 ——
    measure_points: List[MeasurePoint] = field(default_factory=list)
    clustering_config: ClusteringConfig = field(default_factory=ClusteringConfig)

    # ------------------------------------------------------------------ #
    # 构造方法
    # ------------------------------------------------------------------ #

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        """
        从环境变量加载配置

        支持的环境变量：
            GATEWAY_CODE              网关编号
            PROJECT_ID                项目 ID
            MQTT_HOST                 MQTT broker 地址
            MQTT_PORT                 MQTT broker 端口
            MQTT_USERNAME             MQTT 用户名
            MQTT_PASSWORD             MQTT 密码
            MQTT_KEEPALIVE            MQTT 心跳保持（秒）
            HEARTBEAT_INTERVAL        业务心跳间隔（秒）
            MEASURE_POINTS            测点 ID 列表，逗号分隔，如 "MP-001,MP-002"
            CLUSTERING_RADIUS_THRESHOLD  聚类半径阈值 T
            CLUSTERING_MAX_CHILDREN      CF 树最大子节点数 B
            CLUSTERING_THRESHOLD_K       离群判定 k·σ 倍数
            CLUSTERING_CONSECUTIVE_LIMIT 连续离群告警次数
            CLUSTERING_MIN_POINTS        启用 CF 检测前最少点数
            CLUSTERING_MIN_BASELINE_CF   CF 作为基线所需最少点数

        Returns:
            GatewayConfig 实例
        """
        # 解析测点列表
        mp_raw = os.getenv("MEASURE_POINTS", "")
        measure_points: List[MeasurePoint] = []
        if mp_raw.strip():
            for pid in mp_raw.split(","):
                pid = pid.strip()
                if pid:
                    measure_points.append(MeasurePoint(point_id=pid))

        # 默认提供 3 个测点（与 edge-sim 示例一致）
        if not measure_points:
            measure_points = [
                MeasurePoint(point_id=f"MP-{i:03d}")
                for i in range(1, 4)
            ]

        clustering_config = ClusteringConfig(
            radius_threshold=float(os.getenv("CLUSTERING_RADIUS_THRESHOLD", "1.0")),
            max_children=int(os.getenv("CLUSTERING_MAX_CHILDREN", "5")),
            threshold_k=float(os.getenv("CLUSTERING_THRESHOLD_K", "3.0")),
            consecutive_limit=int(os.getenv("CLUSTERING_CONSECUTIVE_LIMIT", "3")),
            min_points_for_detection=int(os.getenv("CLUSTERING_MIN_POINTS", "10")),
            min_baseline_cf_points=int(os.getenv("CLUSTERING_MIN_BASELINE_CF", "2")),
        )

        return cls(
            gateway_code=os.getenv("GATEWAY_CODE", "GW-00000001"),
            project_id=os.getenv("PROJECT_ID", ""),
            mqtt_host=os.getenv("MQTT_HOST", "localhost"),
            mqtt_port=int(os.getenv("MQTT_PORT", "1883")),
            username=os.getenv("MQTT_USERNAME", ""),
            password=os.getenv("MQTT_PASSWORD", ""),
            keepalive=int(os.getenv("MQTT_KEEPALIVE", "60")),
            heartbeat_interval=int(os.getenv("HEARTBEAT_INTERVAL", "30")),
            measure_points=measure_points,
            clustering_config=clustering_config,
        )

    @classmethod
    def from_file(cls, path: str) -> "GatewayConfig":
        """
        从 JSON 文件加载配置

        JSON 结构示例：
            {
              "gateway_code": "GW-00000001",
              "project_id": "PROJ-001",
              "mqtt_host": "localhost",
              "mqtt_port": 1883,
              "username": "",
              "password": "",
              "keepalive": 60,
              "heartbeat_interval": 30,
              "measure_points": [
                {"point_id": "MP-001", "name": "A区-1号", "data_types": [1,2,3,4]}
              ],
              "clustering_config": {
                "radius_threshold": 1.0,
                "max_children": 5,
                "threshold_k": 3.0,
                "consecutive_limit": 3,
                "min_points_for_detection": 10,
                "min_baseline_cf_points": 2
              }
            }

        Args:
            path: JSON 配置文件路径

        Returns:
            GatewayConfig 实例

        Raises:
            FileNotFoundError: 文件不存在
            json.JSONDecodeError: JSON 格式错误
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 解析嵌套结构
        measure_points = [
            MeasurePoint(
                point_id=mp.get("point_id", ""),
                name=mp.get("name", ""),
                data_types=mp.get("data_types", [1, 2, 3, 4]),
            )
            for mp in data.get("measure_points", [])
        ]

        cc_raw = data.get("clustering_config", {})
        clustering_config = ClusteringConfig(
            radius_threshold=cc_raw.get("radius_threshold", 1.0),
            max_children=cc_raw.get("max_children", 5),
            threshold_k=cc_raw.get("threshold_k", 3.0),
            consecutive_limit=cc_raw.get("consecutive_limit", 3),
            min_points_for_detection=cc_raw.get("min_points_for_detection", 10),
            min_baseline_cf_points=cc_raw.get("min_baseline_cf_points", 2),
        )

        return cls(
            gateway_code=data.get("gateway_code", "GW-00000001"),
            project_id=data.get("project_id", ""),
            mqtt_host=data.get("mqtt_host", "localhost"),
            mqtt_port=int(data.get("mqtt_port", 1883)),
            username=data.get("username", ""),
            password=data.get("password", ""),
            keepalive=int(data.get("keepalive", 60)),
            heartbeat_interval=int(data.get("heartbeat_interval", 30)),
            measure_points=measure_points,
            clustering_config=clustering_config,
        )

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """转换为可 JSON 序列化的字典"""
        return asdict(self)

    def to_file(self, path: str) -> None:
        """
        将当前配置写入 JSON 文件

        Args:
            path: 目标文件路径
        """
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def __repr__(self) -> str:
        return (
            f"GatewayConfig(gateway_code={self.gateway_code!r}, "
            f"project_id={self.project_id!r}, "
            f"mqtt={self.mqtt_host}:{self.mqtt_port}, "
            f"measure_points={len(self.measure_points)})"
        )

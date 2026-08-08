"""
BirchAtlas - MQTT 边缘网关客户端
================================

运行在边缘设备（如 Jetson Orin NX）上的 MQTT 通信主模块，负责与云端 EMQX
broker 建立长连接，完成上行数据上报与下行命令接收。

MQTT 主题设计
-------------
上行（边缘 -> 云端）：
    devices/{code}/telemetry        遥测数据（CPU/GPU/内存/推理耗时等）
    devices/{code}/detection        检测结果（钢筋间距 + 离群标注）
    devices/{code}/cf_tree          CF 树增量（BIRCH 聚类特征）
    devices/{code}/heartbeat        心跳
    devices/{code}/shadow/reported  设备影子 reported 状态
    devices/{code}/commands/response 命令响应

下行（云端 -> 边缘）：
    devices/{code}/commands         命令下发
    devices/{code}/shadow/desired   设备影子 desired 状态
    devices/{code}/config           配置下发

QoS 策略
--------
    心跳        QoS=1  （至少一次，保证送达）
    数据上报    QoS=0  （最多一次，允许丢失，吞吐优先）
    命令下发    QoS=2  （恰好一次，避免重复执行）

与 edge.clustering 集成
-----------------------
为每个测点维护一棵 BirchTree 与一个 OutlierDetector，可通过
process_detection_values() 喂入测量值，自动完成离群检测与 CF 树更新，
并通过 publish_cf_tree() 将 CF 树序列化上报云端。

独立运行
--------
    python -m edge.gateway.gateway
    python -m edge.gateway.gateway --mqtt-host localhost --gateway-code GW-00000001
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# 添加项目根目录到 sys.path，便于从包内引用 edge.clustering
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

from edge.clustering import BirchTree, OutlierDetector, CFSerializer

from .config import GatewayConfig
from .command_handler import CommandHandler


# ---------------------------------------------------------------------- #
# 日志格式
# ---------------------------------------------------------------------- #

def _setup_logging(level: int = logging.INFO) -> logging.Logger:
    """配置根日志格式"""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger("edge.gateway")


# ---------------------------------------------------------------------- #
# EdgeGateway 主类
# ---------------------------------------------------------------------- #

class EdgeGateway:
    """
    MQTT 边缘网关客户端

    封装 paho-mqtt 客户端，提供面向 BirchAtlas 业务的上行/下行接口。
    支持自动重连、心跳保活、命令处理与 BIRCH 聚类集成。
    """

    # QoS 常量
    QOS_DATA = 0          # 遥测/检测/CF 树
    QOS_HEARTBEAT = 1     # 心跳
    QOS_COMMAND = 2       # 命令

    def __init__(
        self,
        gateway_code: str,
        mqtt_host: str,
        mqtt_port: int = 1883,
        username: str = "",
        password: str = "",
        config: Optional[GatewayConfig] = None,
        keepalive: int = 60,
    ) -> None:
        """
        初始化边缘网关

        Args:
            gateway_code: 网关唯一编号（如 "GW-00000001"）
            mqtt_host:    MQTT broker 地址
            mqtt_port:    MQTT broker 端口
            username:     MQTT 用户名（可空）
            password:     MQTT 密码（可空）
            config:       网关完整配置（可空，为空时使用入参构造一份默认配置）
            keepalive:    MQTT 心跳保持时长（秒）
        """
        self.gateway_code = gateway_code
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.username = username
        self.password = password
        self.keepalive = keepalive

        # 如果调用方未提供 config，则用入参拼装一份（保证字段一致）
        self.config: GatewayConfig = config or GatewayConfig(
            gateway_code=gateway_code,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            username=username,
            password=password,
            keepalive=keepalive,
        )

        self.logger = logging.getLogger("edge.gateway.EdgeGateway")

        # ---------------- 主题定义 ----------------
        base = f"devices/{self.gateway_code}"
        self.topic_telemetry = f"{base}/telemetry"
        self.topic_detection = f"{base}/detection"
        self.topic_cf_tree = f"{base}/cf_tree"
        self.topic_heartbeat = f"{base}/heartbeat"
        self.topic_shadow_reported = f"{base}/shadow/reported"
        self.topic_commands_response = f"{base}/commands/response"

        self.topic_commands = f"{base}/commands"
        self.topic_shadow_desired = f"{base}/shadow/desired"
        self.topic_config = f"{base}/config"

        # ---------------- 运行状态 ----------------
        self._connected = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._detection_thread: Optional[threading.Thread] = None
        self._detection_stop = threading.Event()

        # ---------------- 聚类状态（每个测点一份） ----------------
        self._clusterers: Dict[str, Dict[str, Any]] = {}
        self._init_clusterers()

        # ---------------- 命令处理器 ----------------
        self.command_handler = CommandHandler(
            config=self.config,
            callbacks={
                "publish_cf_tree": self._cb_publish_cf_tree,
                "publish_shadow": self._cb_publish_shadow,
                "apply_config": self._cb_apply_config,
                "start_detection": self._cb_start_detection,
                "stop_detection": self._cb_stop_detection,
                "reboot": self._cb_reboot,
                "ota_upgrade": self._cb_ota_upgrade,
            },
        )

        # ---------------- MQTT 客户端 ----------------
        self._client: mqtt.Client = mqtt.Client(
            CallbackAPIVersion.VERSION2,
            client_id=f"edge-gw-{self.gateway_code}",
            clean_session=True,
        )
        if self.username:
            self._client.username_pw_set(self.username, self.password)

        # 设置遗嘱消息（LWT）：异常断开时由 broker 代发下线状态
        lwt_payload = json.dumps({
            "gateway_code": self.gateway_code,
            "status": "offline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)
        self._client.will_set(
            self.topic_heartbeat, lwt_payload, qos=self.QOS_HEARTBEAT, retain=True,
        )

        # 注册回调
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # 自动重连：1s 起步，最长 120s
        self._client.reconnect_delay_set(min_delay=1, max_delay=120)

    # ------------------------------------------------------------------ #
    # 聚类初始化
    # ------------------------------------------------------------------ #

    def _init_clusterers(self) -> None:
        """根据 config.measure_points 为每个测点创建 BIRCH 树与离群检测器"""
        cc = self.config.clustering_config
        for mp in self.config.measure_points:
            birch_tree = BirchTree(
                radius_threshold=cc.radius_threshold,
                max_children=cc.max_children,
                outlier_threshold_k=cc.threshold_k,
                consecutive_outlier_limit=cc.consecutive_limit,
            )
            detector = OutlierDetector(
                birch_tree=birch_tree,
                threshold_k=cc.threshold_k,
                consecutive_limit=cc.consecutive_limit,
                min_points_for_detection=cc.min_points_for_detection,
                min_baseline_cf_points=cc.min_baseline_cf_points,
            )
            self._clusterers[mp.point_id] = {
                "measure_point": mp,
                "birch_tree": birch_tree,
                "detector": detector,
                "stats": {
                    "total_records": 0,
                    "total_values": 0,
                    "outliers_found": 0,
                },
            }
            self.logger.info("已初始化测点聚类器: %s", mp.point_id)

    # ------------------------------------------------------------------ #
    # 连接 / 断开
    # ------------------------------------------------------------------ #

    def connect(self) -> bool:
        """
        连接到 MQTT broker（同步）

        连接成功后启动网络循环线程，并触发 on_connect 自动订阅下行主题。
        若 broker 不可达，paho-mqtt 会按 reconnect_delay_set 的策略自动重连。

        Returns:
            是否在 5s 内建立连接
        """
        self.logger.info("正在连接 MQTT broker %s:%d ...", self.mqtt_host, self.mqtt_port)
        try:
            self._client.connect(self.mqtt_host, self.mqtt_port, keepalive=self.keepalive)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "初次连接失败: %s，启动后台自动重连...", exc,
            )
        # 无论初次连接是否成功，都启动网络循环，让 paho 自动重连
        self._client.loop_start()
        # 等待连接建立（最多 5 秒）
        connected = self._connected.wait(timeout=5.0)
        if connected:
            self.logger.info("MQTT 连接已建立")
        else:
            self.logger.warning("MQTT 连接尚未建立，后台将持续重连")
        return connected

    def disconnect(self) -> None:
        """断开 MQTT 连接，停止心跳与检测线程"""
        self.logger.info("正在断开 MQTT 连接...")
        self.stop_heartbeat()
        self.stop_detection_loop()
        try:
            # 发布下线状态（清除 retain 心跳）
            offline_payload = json.dumps({
                "gateway_code": self.gateway_code,
                "status": "offline",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False)
            self._client.publish(
                self.topic_heartbeat, offline_payload,
                qos=self.QOS_HEARTBEAT, retain=True,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("发布下线状态失败: %s", exc)

        self._client.loop_stop()
        self._client.disconnect()
        self._connected.clear()
        self.logger.info("MQTT 已断开")

    # ------------------------------------------------------------------ #
    # paho-mqtt 回调
    # ------------------------------------------------------------------ #

    def _on_connect(self, client: mqtt.Client, userdata: Any,
                    flags: Dict, reason_code: int, properties: Any) -> None:
        """
        连接成功回调：自动订阅下行主题

        当 reason_code 非 0 时（如认证失败）仅记录日志不订阅。
        """
        if reason_code != 0:
            self.logger.error("MQTT 连接失败，reason_code=%s", reason_code)
            self._connected.clear()
            return

        self.logger.info("MQTT 连接成功 (reason_code=%s)，开始订阅下行主题", reason_code)
        self._connected.set()

        # 订阅下行主题（命令 QoS=2，影子/配置 QoS=1）
        subscribe_list = [
            (self.topic_commands, self.QOS_COMMAND),
            (self.topic_shadow_desired, self.QOS_HEARTBEAT),
            (self.topic_config, self.QOS_HEARTBEAT),
        ]
        result, _ = client.subscribe(subscribe_list)
        if result == mqtt.MQTT_ERR_SUCCESS:
            self.logger.info("已订阅下行主题: %s", subscribe_list)
        else:
            self.logger.error("订阅下行主题失败: result=%s", result)

        # 上报在线状态
        self.publish_shadow({"status": "online", "connected_at": _now_iso()})

    def _on_disconnect(self, client: mqtt.Client, userdata: Any,
                       flags: Dict, reason_code: int, properties: Any) -> None:
        """连接断开回调：记录日志，paho 会自动重连"""
        self.logger.warning("MQTT 连接断开 (reason_code=%s)，等待自动重连", reason_code)
        self._connected.clear()

    def _on_message(self, client: mqtt.Client, userdata: Any, message: mqtt.MQTTMessage) -> None:
        """
        消息回调：根据 topic 分发到不同处理器

        - commands:       命令处理
        - shadow/desired: 影子 desired 状态更新
        - config:         配置下发
        """
        topic = message.topic
        try:
            payload_str = message.payload.decode("utf-8", errors="replace")
            payload = json.loads(payload_str) if payload_str else {}
        except json.JSONDecodeError as exc:
            self.logger.error("消息 JSON 解析失败 topic=%s: %s", topic, exc)
            return
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("消息处理异常 topic=%s: %s", topic, exc)
            return

        self.logger.debug("收到消息 topic=%s, qos=%s", topic, message.qos)

        if topic == self.topic_commands:
            self._handle_command_message(payload)
        elif topic == self.topic_shadow_desired:
            self._handle_shadow_desired(payload)
        elif topic == self.topic_config:
            self._handle_config_message(payload)
        else:
            self.logger.debug("未识别的 topic，忽略: %s", topic)

    # ------------------------------------------------------------------ #
    # 下行消息处理
    # ------------------------------------------------------------------ #

    def _handle_command_message(self, payload: Dict) -> None:
        """处理 devices/{code}/commands 下发的命令"""
        response = self.command_handler.handle_command(payload)

        # 在响应中带上原命令 ID（便于云端匹配）
        cmd_id = payload.get("cmd_id") or payload.get("id")
        if cmd_id is not None:
            response["cmd_id"] = cmd_id
        response["gateway_code"] = self.gateway_code
        response["timestamp"] = _now_iso()

        self._publish_json(self.topic_commands_response, response, qos=self.QOS_COMMAND)

    def _handle_shadow_desired(self, payload: Dict) -> None:
        """
        处理 devices/{code}/shadow/desired：云端下发的期望状态

        简化策略：将 desired 中的字段合并到本地 shadow_state，
        然后立即上报 reported 以完成影子同步。
        """
        desired = payload.get("state", {}).get("desired", payload)
        self.logger.info("收到影子 desired: %s", desired)
        for k, v in desired.items():
            self.command_handler.update_shadow(k, v)
        # 上报合并后的 reported
        self.publish_shadow(self.command_handler.shadow_state)

    def _handle_config_message(self, payload: Dict) -> None:
        """处理 devices/{code}/config：配置下发（与 config_update 命令等价）"""
        self.logger.info("收到配置下发: %s", payload)
        # 复用命令处理器
        self.command_handler.handle_command({
            "type": "config_update",
            "payload": payload,
        })

    # ------------------------------------------------------------------ #
    # 上行发布接口
    # ------------------------------------------------------------------ #

    def publish_telemetry(self, data: Dict) -> None:
        """
        发布遥测数据到 devices/{code}/telemetry (QoS=0)

        Args:
            data: 遥测数据字典（CPU/GPU/内存/网络/推理耗时等）
        """
        payload = self._wrap_payload(data)
        self._publish_json(self.topic_telemetry, payload, qos=self.QOS_DATA)

    def publish_detection_result(self, result: Dict) -> None:
        """
        发布检测结果到 devices/{code}/detection (QoS=0)

        Args:
            result: 检测结果字典（钢筋间距记录 + 离群标注 + 聚类快照）
        """
        payload = self._wrap_payload(result)
        self._publish_json(self.topic_detection, payload, qos=self.QOS_DATA)

    def publish_cf_tree(self, cf_data: Dict) -> None:
        """
        发布 CF 树到 devices/{code}/cf_tree (QoS=0)

        Args:
            cf_data: CFSerializer.to_json() 返回的字典
        """
        payload = self._wrap_payload(cf_data)
        self._publish_json(self.topic_cf_tree, payload, qos=self.QOS_DATA)

    def publish_heartbeat(self) -> None:
        """发布心跳到 devices/{code}/heartbeat (QoS=1, retain=True)"""
        payload = self._wrap_payload({
            "status": "online",
            "uptime_seconds": int(time.time() - self._start_time),
            "clusterers": len(self._clusterers),
        })
        self._publish_json(
            self.topic_heartbeat, payload,
            qos=self.QOS_HEARTBEAT, retain=True,
        )

    def publish_shadow(self, reported_state: Dict) -> None:
        """
        上报设备影子 reported 状态到 devices/{code}/shadow/reported (QoS=1)

        Args:
            reported_state: reported 状态字典
        """
        # 同步更新本地缓存
        for k, v in reported_state.items():
            self.command_handler.update_shadow(k, v)

        payload = self._wrap_payload({"state": {"reported": reported_state}})
        self._publish_json(
            self.topic_shadow_reported, payload,
            qos=self.QOS_HEARTBEAT, retain=True,
        )

    def subscribe_commands(self) -> None:
        """
        显式订阅命令主题 devices/{code}/commands (QoS=2)

        通常无需手动调用：on_connect 回调会自动订阅。
        本方法用于运行时重新订阅的场景。
        """
        if not self._connected.is_set():
            self.logger.warning("尚未连接，无法订阅命令主题")
            return
        self._client.subscribe(self.topic_commands, qos=self.QOS_COMMAND)
        self.logger.info("已显式订阅命令主题: %s", self.topic_commands)

    # ------------------------------------------------------------------ #
    # 心跳线程
    # ------------------------------------------------------------------ #

    def start_heartbeat(self, interval: int = 30) -> None:
        """
        启动后台心跳线程

        Args:
            interval: 心跳间隔（秒），默认 30
        """
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self.logger.warning("心跳线程已在运行")
            return

        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval,),
            name="edge-gw-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        self.logger.info("心跳线程已启动，间隔 %d 秒", interval)

    def stop_heartbeat(self) -> None:
        """停止心跳线程"""
        if self._heartbeat_thread is None or not self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.set()
        self._heartbeat_thread.join(timeout=5.0)
        self._heartbeat_thread = None
        self.logger.info("心跳线程已停止")

    def _heartbeat_loop(self, interval: int) -> None:
        """心跳循环（在线程中运行）"""
        while not self._heartbeat_stop.is_set():
            try:
                if self._connected.is_set():
                    self.publish_heartbeat()
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("心跳发布异常: %s", exc)
            # 使用 wait 代替 sleep，便于快速响应停止信号
            self._heartbeat_stop.wait(interval)

    # ------------------------------------------------------------------ #
    # 阻塞运行
    # ------------------------------------------------------------------ #

    def loop_forever(self) -> None:
        """
        阻塞运行网络循环

        内部调用 paho 的 loop_forever()，会阻塞当前线程并处理所有网络事件。
        与 loop_start() 互斥；若已调用 connect()（其内部已 loop_start），
        请先 loop_stop() 再调用本方法，或直接使用 connect() + 主线程等待。
        """
        self.logger.info("进入阻塞网络循环 (loop_forever)")
        try:
            self._client.loop_forever(retry_first_connection=True)
        except KeyboardInterrupt:
            self.logger.info("收到 Ctrl+C，准备退出")
            self.disconnect()

    # ------------------------------------------------------------------ #
    # 聚类业务集成
    # ------------------------------------------------------------------ #

    def process_detection_values(
        self,
        measure_point_id: str,
        data_type: int,
        values: List[float],
    ) -> Dict[str, Any]:
        """
        处理一批检测值：运行离群检测并更新 CF 树

        Args:
            measure_point_id: 测点编号
            data_type:        数据类型 (1=底横筋 2=底纵筋 3=面横筋 4=面纵筋)
            values:           间距值列表

        Returns:
            检测结果字典，包含 outlier_indices / cluster_snapshot / stats
        """
        clusterer = self._clusterers.get(measure_point_id)
        if clusterer is None:
            self.logger.warning("未知测点: %s", measure_point_id)
            return {"success": False, "message": f"未知测点: {measure_point_id}"}

        detector: OutlierDetector = clusterer["detector"]
        birch_tree: BirchTree = clusterer["birch_tree"]

        # 批量离群检测（内部会自动更新 CF 树）
        detection_results = detector.detect_batch(values)

        outlier_indices = [
            i for i, r in enumerate(detection_results) if r["is_outlier"]
        ]
        clusterer["stats"]["total_values"] += len(values)
        clusterer["stats"]["outliers_found"] += len(outlier_indices)
        clusterer["stats"]["total_records"] += 1

        return {
            "success": True,
            "measure_point_id": measure_point_id,
            "data_type": data_type,
            "values": values,
            "detection_results": detection_results,
            "outlier_indices": outlier_indices,
            "cluster_snapshot": {
                "clusters": birch_tree.get_clusters(),
                "stats": birch_tree.get_stats(),
            },
        }

    def get_cf_tree_data(self, measure_point_id: str,
                         data_type: str = "mixed") -> Optional[Dict]:
        """
        获取指定测点的 CF 树序列化数据

        Args:
            measure_point_id: 测点编号
            data_type:        数据类型标签（用于 tree_id）

        Returns:
            CFSerializer.to_json() 返回的字典；测点不存在时返回 None
        """
        clusterer = self._clusterers.get(measure_point_id)
        if clusterer is None:
            return None
        tree: BirchTree = clusterer["birch_tree"]
        return CFSerializer.to_json(
            tree,
            gateway_code=self.gateway_code,
            measure_point_id=measure_point_id,
            data_type=data_type,
        )

    # ------------------------------------------------------------------ #
    # 命令处理器的回调实现
    # ------------------------------------------------------------------ #

    def _cb_publish_cf_tree(self, payload: Dict) -> None:
        """命令 upload_cf_tree 触发：上传 CF 树"""
        measure_point_id = payload.get("measure_point_id")
        if measure_point_id:
            # 上传指定测点
            cf_data = self.get_cf_tree_data(measure_point_id)
            if cf_data:
                self.publish_cf_tree(cf_data)
            else:
                self.logger.warning("命令要求上传未知测点的 CF 树: %s", measure_point_id)
        else:
            # 上传全部测点
            for mp_id in self._clusterers:
                cf_data = self.get_cf_tree_data(mp_id)
                if cf_data:
                    self.publish_cf_tree(cf_data)

    def _cb_publish_shadow(self, payload: Dict) -> None:
        """命令 sync_shadow 触发：上报设备影子"""
        reported = payload.get("reported") or self.command_handler.shadow_state
        self.publish_shadow(reported)

    def _cb_apply_config(self, payload: Dict) -> None:
        """命令 config_update 触发：应用新配置（当前仅记录，不重建聚类器）"""
        self.logger.info("配置已更新: %s", payload.get("config"))

    def _cb_start_detection(self, payload: Dict) -> None:
        """命令 start_detection 触发：启动检测循环"""
        self.start_detection_loop()

    def _cb_stop_detection(self, payload: Dict) -> None:
        """命令 stop_detection 触发：停止检测循环"""
        self.stop_detection_loop()

    def _cb_reboot(self, payload: Dict) -> None:
        """命令 reboot 触发：实际重启动作由部署环境实现（此处仅记录）"""
        self.logger.warning("设备重启 callback 未实现，请在外部注册 reboot 回调以真正重启")

    def _cb_ota_upgrade(self, payload: Dict) -> None:
        """命令 ota_upgrade 触发：实际 OTA 动作由部署环境实现"""
        self.logger.warning(
            "OTA 升级 callback 未实现 (version=%s)，请在外部注册 ota_upgrade 回调",
            payload.get("version"),
        )

    # ------------------------------------------------------------------ #
    # 演示用检测循环（独立运行时使用）
    # ------------------------------------------------------------------ #

    def start_detection_loop(self, interval_ms: int = 1000) -> None:
        """
        启动演示用检测循环线程

        生成合成钢筋间距数据 → 离群检测 → 上报检测结果与遥测。
        真实部署时建议替换为本地的真实数据采集逻辑。

        Args:
            interval_ms: 检测周期（毫秒）
        """
        if self._detection_thread and self._detection_thread.is_alive():
            self.logger.warning("检测循环已在运行")
            return

        self._detection_stop.clear()
        self._detection_thread = threading.Thread(
            target=self._detection_loop,
            args=(interval_ms,),
            name="edge-gw-detection",
            daemon=True,
        )
        self._detection_thread.start()
        self.logger.info("检测循环已启动，周期 %d ms", interval_ms)

    def stop_detection_loop(self) -> None:
        """停止演示用检测循环线程"""
        if self._detection_thread is None or not self._detection_thread.is_alive():
            return
        self._detection_stop.set()
        self._detection_thread.join(timeout=5.0)
        self._detection_thread = None
        self.logger.info("检测循环已停止")

    def _detection_loop(self, interval_ms: int) -> None:
        """演示检测循环（线程中运行）"""
        # 复用 edge-sim 的数据生成思路（简化版）
        # 数据类型基线：1=底横筋 2=底纵筋 3=面横筋 4=面纵筋
        baseline = {
            1: (300.0, 5.0, 5),
            2: (150.0, 3.0, 8),
            3: (250.0, 4.0, 6),
            4: (200.0, 3.5, 7),
        }
        import random

        while not self._detection_stop.is_set():
            try:
                if not self._connected.is_set():
                    # 未连接时仅等待
                    self._detection_stop.wait(interval_ms / 1000.0)
                    continue

                for mp_id, clusterer in self._clusterers.items():
                    mp: Any = clusterer["measure_point"]
                    # 为该测点的每种数据类型生成一批值并检测
                    all_results = []
                    for data_type in mp.data_types:
                        mean, std, count = baseline.get(data_type, (200.0, 5.0, 5))
                        # 10% 概率注入异常
                        vals = []
                        for _ in range(count):
                            if random.random() < 0.1:
                                vals.append(round(mean * random.choice([0.5, 1.5, 2.0])
                                                  + random.gauss(0, std), 1))
                            else:
                                vals.append(round(mean + random.gauss(0, std), 1))
                        result = self.process_detection_values(mp_id, data_type, vals)
                        all_results.append({
                            "type": data_type,
                            "vals": vals,
                            "outlier_indices": result.get("outlier_indices", []),
                        })

                    # 上报检测结果
                    detection_payload = {
                        "measure_point_id": mp_id,
                        "record_time": _now_iso(),
                        "data_list": all_results,
                        "cluster_snapshot": clusterer["birch_tree"].get_stats(),
                    }
                    self.publish_detection_result(detection_payload)

                # 上报遥测
                self._publish_demo_telemetry()

                # 每 10 个周期上报一次 CF 树
                self._demo_cycle = getattr(self, "_demo_cycle", 0) + 1
                if self._demo_cycle % 10 == 0:
                    for mp_id in self._clusterers:
                        cf_data = self.get_cf_tree_data(mp_id)
                        if cf_data:
                            self.publish_cf_tree(cf_data)

            except Exception as exc:  # noqa: BLE001
                self.logger.exception("检测循环异常: %s", exc)

            self._detection_stop.wait(interval_ms / 1000.0)

    def _publish_demo_telemetry(self) -> None:
        """生成并上报演示遥测数据"""
        import random
        total_points = sum(
            c["birch_tree"].total_points_processed
            for c in self._clusterers.values()
        )
        telemetry = {
            "device_code": self.gateway_code,
            "timestamp": _now_iso(),
            "cpu": {
                "usage_percent": round(random.uniform(30, 85), 1),
                "temperature_celsius": round(random.uniform(45, 65), 1),
            },
            "memory": {
                "used_mb": random.randint(1500, 3500),
                "total_mb": 8192,
            },
            "clustering": {
                "cf_tree_size": total_points,
                "total_points_processed": total_points,
                "total_outliers_detected": sum(
                    c["stats"]["outliers_found"] for c in self._clusterers.values()
                ),
            },
        }
        self.publish_telemetry(telemetry)

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #

    @property
    def _start_time(self) -> float:
        """进程启动时间（用于心跳中的 uptime）"""
        if not hasattr(self, "_start_ts"):
            self._start_ts = time.time()
        return self._start_ts

    def _wrap_payload(self, data: Dict) -> Dict:
        """为上行数据附加网关编号与时间戳"""
        wrapped = dict(data) if isinstance(data, dict) else {"data": data}
        wrapped.setdefault("gateway_code", self.gateway_code)
        wrapped.setdefault("timestamp", _now_iso())
        return wrapped

    def _publish_json(self, topic: str, payload: Dict,
                      qos: int = 0, retain: bool = False) -> None:
        """发布 JSON 消息"""
        if not self._connected.is_set():
            self.logger.debug("未连接，跳过发布: %s", topic)
            return
        try:
            message = json.dumps(payload, ensure_ascii=False)
            self._client.publish(topic, message, qos=qos, retain=retain)
            self.logger.debug(">>> %s (qos=%s): %s", topic, qos, _truncate(message, 120))
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("发布消息失败 topic=%s: %s", topic, exc)

    # ------------------------------------------------------------------ #
    # repr
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        return (
            f"EdgeGateway(code={self.gateway_code!r}, "
            f"mqtt={self.mqtt_host}:{self.mqtt_port}, "
            f"measure_points={len(self._clusterers)})"
        )


# ---------------------------------------------------------------------- #
# 辅助函数
# ---------------------------------------------------------------------- #

def _now_iso() -> str:
    """当前 UTC 时间的 ISO 字符串"""
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, max_len: int) -> str:
    """截断长字符串用于日志展示"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


# ---------------------------------------------------------------------- #
# CLI 入口
# ---------------------------------------------------------------------- #

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BirchAtlas 边缘网关 MQTT 客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用环境变量配置启动
  python -m edge.gateway.gateway

  # 指定 broker 与网关编号
  python -m edge.gateway.gateway --mqtt-host localhost --gateway-code GW-00000001

  # 从配置文件启动
  python -m edge.gateway.gateway --config gateway.json

  # 启用演示检测循环
  python -m edge.gateway.gateway --enable-demo
        """,
    )
    parser.add_argument("--gateway-code", default=None,
                        help="网关编号（默认读环境变量 GATEWAY_CODE 或 GW-00000001）")
    parser.add_argument("--mqtt-host", default=None,
                        help="MQTT broker 地址（默认读环境变量 MQTT_HOST 或 localhost）")
    parser.add_argument("--mqtt-port", type=int, default=None,
                        help="MQTT broker 端口（默认读环境变量 MQTT_PORT 或 1883）")
    parser.add_argument("--username", default=None, help="MQTT 用户名")
    parser.add_argument("--password", default=None, help="MQTT 密码")
    parser.add_argument("--config", default=None,
                        help="JSON 配置文件路径（优先级高于命令行参数）")
    parser.add_argument("--enable-demo", action="store_true",
                        help="启用演示检测循环（生成合成数据）")
    parser.add_argument("--heartbeat-interval", type=int, default=None,
                        help="心跳间隔（秒），默认 30")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别（默认 INFO）")
    return parser.parse_args()


def main() -> None:
    """CLI 主入口"""
    args = _parse_args()
    logger = _setup_logging(getattr(logging, args.log_level))

    # ---------------- 加载配置 ----------------
    if args.config:
        config = GatewayConfig.from_file(args.config)
        logger.info("从文件加载配置: %s", args.config)
    else:
        config = GatewayConfig.from_env()

    # 命令行参数覆盖（优先级最高）
    if args.gateway_code:
        config.gateway_code = args.gateway_code
    if args.mqtt_host:
        config.mqtt_host = args.mqtt_host
    if args.mqtt_port:
        config.mqtt_port = args.mqtt_port
    if args.username is not None:
        config.username = args.username
    if args.password is not None:
        config.password = args.password
    if args.heartbeat_interval:
        config.heartbeat_interval = args.heartbeat_interval

    logger.info("配置加载完成: %s", config)

    # ---------------- 创建网关 ----------------
    gateway = EdgeGateway(
        gateway_code=config.gateway_code,
        mqtt_host=config.mqtt_host,
        mqtt_port=config.mqtt_port,
        username=config.username,
        password=config.password,
        config=config,
        keepalive=config.keepalive,
    )

    # ---------------- 信号处理 ----------------
    def _signal_handler(signum, frame):
        logger.info("收到信号 %s，准备退出...", signum)
        gateway.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # ---------------- 启动 ----------------
    gateway.connect()
    gateway.start_heartbeat(interval=config.heartbeat_interval)

    if args.enable_demo:
        gateway.start_detection_loop(interval_ms=1000)
        logger.info("演示检测循环已启用")

    # 阻塞运行
    logger.info("边缘网关已启动，按 Ctrl+C 退出")
    gateway.loop_forever()


if __name__ == "__main__":
    main()

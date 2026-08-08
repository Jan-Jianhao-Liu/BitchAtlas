"""
BirchAtlas - 云端命令处理器
===========================

处理云端通过 MQTT 下发的命令（devices/{code}/commands），并返回统一的响应结构。

支持的命令类型：
    config_update    更新网关配置（如聚类阈值、心跳间隔）
    start_detection  开始检测循环
    stop_detection   停止检测循环
    sync_shadow      主动同步设备影子状态
    ota_upgrade      OTA 升级指令（A/B 分区切换）
    upload_cf_tree   立即上传当前 CF 树
    reboot           重启设备

响应格式统一为：
    {"success": bool, "message": str, "data": dict}

CommandHandler 通过 callbacks 字典与外部（EdgeGateway）解耦：
对于自身无法完成的副作用（如真正发布 CF 树、真正重启设备），
会调用对应 callback；若未注册则只更新内部状态并记录日志。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from .config import GatewayConfig


class CommandHandler:
    """
    云端命令处理器

    线程安全说明：本类主要在 MQTT 网络回调线程中被调用，
    对内部状态的读写应避免与主线程并发冲突；外部业务线程读取
    detection_running 等标志时请自行加锁或仅作提示性使用。
    """

    # 支持的命令类型列表（便于外部展示/校验）
    SUPPORTED_COMMANDS = (
        "config_update",
        "start_detection",
        "stop_detection",
        "sync_shadow",
        "ota_upgrade",
        "upload_cf_tree",
        "reboot",
    )

    def __init__(
        self,
        config: Optional[GatewayConfig] = None,
        callbacks: Optional[Dict[str, Callable[[Dict], Any]]] = None,
    ) -> None:
        """
        初始化命令处理器

        Args:
            config: 网关配置（可被 config_update 命令更新）
            callbacks: 回调函数字典，可包含以下键：
                - "publish_cf_tree": 上传 CF 树到云端
                - "publish_shadow":  上报设备影子
                - "reboot":          实际重启设备
                - "ota_upgrade":     实际执行 OTA 升级
                - "apply_config":    应用新配置到 EdgeGateway
                - "start_detection": 启动检测循环
                - "stop_detection":  停止检测循环
                每个回调接收一个 dict 参数，返回值忽略。
        """
        self.logger = logging.getLogger(__name__)
        self.config: GatewayConfig = config or GatewayConfig()

        # 运行状态
        self.detection_running: bool = False
        self.shadow_state: Dict[str, Any] = {
            "status": "online",
            "last_command_at": None,
            "last_command_type": None,
            "version": "0.1.0",
        }

        # 回调表
        self.callbacks: Dict[str, Callable[[Dict], Any]] = dict(callbacks or {})

        # 命令分发表
        self._handlers: Dict[str, Callable[[Dict], Dict]] = {
            "config_update": self._handle_config_update,
            "start_detection": self._handle_start_detection,
            "stop_detection": self._handle_stop_detection,
            "sync_shadow": self._handle_sync_shadow,
            "ota_upgrade": self._handle_ota_upgrade,
            "upload_cf_tree": self._handle_upload_cf_tree,
            "reboot": self._handle_reboot,
        }

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #

    def handle_command(self, cmd: Dict) -> Dict:
        """
        处理云端下发的命令

        Args:
            cmd: 命令字典，必须包含 "type"/"cmd"/"command" 之一作为命令类型，
                 其余字段作为命令参数。

        Returns:
            统一响应：{"success": bool, "message": str, "data": dict}
        """
        # 兼容多种命令字段命名
        cmd_type = cmd.get("type") or cmd.get("cmd") or cmd.get("command")
        if not cmd_type:
            return self._fail("命令缺少 type/cmd/command 字段")

        handler = self._handlers.get(cmd_type)
        if handler is None:
            self.logger.warning("收到不支持的命令类型: %s", cmd_type)
            return self._fail(f"不支持的命令类型: {cmd_type}")

        # 记录命令到达时间
        self.shadow_state["last_command_at"] = datetime.now(timezone.utc).isoformat()
        self.shadow_state["last_command_type"] = cmd_type

        self.logger.info("处理云端命令: %s, payload=%s", cmd_type, cmd)
        try:
            response = handler(cmd)
        except Exception as exc:  # noqa: BLE001 - 兜底防止回调线程崩溃
            self.logger.exception("命令处理异常: %s", cmd_type)
            return self._fail(f"命令处理异常: {exc}")

        self.logger.info("命令 %s 处理结果: success=%s", cmd_type, response.get("success"))
        return response

    # ------------------------------------------------------------------ #
    # 各命令的具体实现
    # ------------------------------------------------------------------ #

    def _handle_config_update(self, cmd: Dict) -> Dict:
        """
        config_update: 更新网关配置

        命令参数（可选）：
            payload: {
                "clustering_config": {...},
                "heartbeat_interval": 30,
                "measure_points": [...]
            }
        """
        payload = cmd.get("payload") or cmd.get("data") or {}

        updated_fields: Dict[str, Any] = {}

        # 更新心跳间隔
        if "heartbeat_interval" in payload:
            new_interval = int(payload["heartbeat_interval"])
            if new_interval > 0:
                self.config.heartbeat_interval = new_interval
                updated_fields["heartbeat_interval"] = new_interval

        # 更新聚类配置
        cc_raw = payload.get("clustering_config")
        if isinstance(cc_raw, dict):
            cc = self.config.clustering_config
            if "radius_threshold" in cc_raw:
                cc.radius_threshold = float(cc_raw["radius_threshold"])
            if "max_children" in cc_raw:
                cc.max_children = int(cc_raw["max_children"])
            if "threshold_k" in cc_raw:
                cc.threshold_k = float(cc_raw["threshold_k"])
            if "consecutive_limit" in cc_raw:
                cc.consecutive_limit = int(cc_raw["consecutive_limit"])
            if "min_points_for_detection" in cc_raw:
                cc.min_points_for_detection = int(cc_raw["min_points_for_detection"])
            if "min_baseline_cf_points" in cc_raw:
                cc.min_baseline_cf_points = int(cc_raw["min_baseline_cf_points"])
            updated_fields["clustering_config"] = asdict_safe(cc)

        # 通知外部应用新配置
        self._invoke_callback("apply_config", {"config": self.config.to_dict()})

        return self._ok(
            "配置已更新",
            {"updated_fields": updated_fields, "current_config": self.config.to_dict()},
        )

    def _handle_start_detection(self, cmd: Dict) -> Dict:
        """
        start_detection: 开始检测循环
        """
        if self.detection_running:
            return self._ok("检测已在运行中", {"detection_running": True})

        self.detection_running = True
        self._invoke_callback("start_detection", cmd)
        return self._ok("检测已启动", {"detection_running": True})

    def _handle_stop_detection(self, cmd: Dict) -> Dict:
        """
        stop_detection: 停止检测循环
        """
        if not self.detection_running:
            return self._ok("检测未在运行", {"detection_running": False})

        self.detection_running = False
        self._invoke_callback("stop_detection", cmd)
        return self._ok("检测已停止", {"detection_running": False})

    def _handle_sync_shadow(self, cmd: Dict) -> Dict:
        """
        sync_shadow: 主动同步设备影子

        云端要求设备立即上报当前 reported 状态。
        """
        shadow = dict(self.shadow_state)
        shadow["synced_at"] = datetime.now(timezone.utc).isoformat()
        self._invoke_callback("publish_shadow", {"reported": shadow})
        return self._ok("设备影子已同步", {"shadow": shadow})

    def _handle_ota_upgrade(self, cmd: Dict) -> Dict:
        """
        ota_upgrade: OTA 升级指令

        命令参数：
            payload: {
                "version": "0.2.0",
                "package_url": "https://...",
                "signature": "...",
                "target_partition": "B"
            }

        安全说明：实际下载/验签/切换分区应由注册的 "ota_upgrade" callback 完成；
        本处理器仅做参数校验与状态记录。
        """
        payload = cmd.get("payload") or cmd.get("data") or {}
        version = payload.get("version")
        package_url = payload.get("package_url")

        if not version or not package_url:
            return self._fail("OTA 升级缺少 version 或 package_url 参数")

        self.logger.info("OTA 升级请求: version=%s, url=%s", version, package_url)
        self._invoke_callback("ota_upgrade", {
            "version": version,
            "package_url": package_url,
            "signature": payload.get("signature", ""),
            "target_partition": payload.get("target_partition", "B"),
        })

        return self._ok(
            "OTA 升级指令已接受，正在后台执行",
            {
                "target_version": version,
                "current_version": self.shadow_state.get("version"),
                "target_partition": payload.get("target_partition", "B"),
            },
        )

    def _handle_upload_cf_tree(self, cmd: Dict) -> Dict:
        """
        upload_cf_tree: 立即上传当前 CF 树

        云端可指定 measure_point_id；未指定则上传全部测点。
        """
        payload = cmd.get("payload") or cmd.get("data") or {}
        measure_point_id = payload.get("measure_point_id")

        self._invoke_callback("publish_cf_tree", {
            "measure_point_id": measure_point_id,
            "trigger": "cloud_command",
        })

        return self._ok(
            "CF 树上传已触发",
            {
                "measure_point_id": measure_point_id or "all",
                "triggered_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _handle_reboot(self, cmd: Dict) -> Dict:
        """
        reboot: 重启设备

        实际重启动作应由注册的 "reboot" callback 完成；
        若未注册，则仅记录日志并返回（便于在开发环境安全测试）。
        """
        self.logger.warning("收到设备重启命令，准备重启...")
        self._invoke_callback("reboot", cmd)
        return self._ok(
            "重启命令已接受",
            {"reboot_at": datetime.now(timezone.utc).isoformat()},
        )

    # ------------------------------------------------------------------ #
    # 辅助方法
    # ------------------------------------------------------------------ #

    def update_shadow(self, key: str, value: Any) -> None:
        """更新设备影子 reported 状态中的某个字段"""
        self.shadow_state[key] = value

    def register_callback(self, name: str, fn: Callable[[Dict], Any]) -> None:
        """注册单个回调函数"""
        self.callbacks[name] = fn

    def _invoke_callback(self, name: str, payload: Dict) -> None:
        """安全调用回调（捕获异常防止崩溃网络线程）"""
        fn = self.callbacks.get(name)
        if fn is None:
            self.logger.debug("回调未注册，跳过: %s", name)
            return
        try:
            fn(payload)
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("回调 %s 执行异常: %s", name, exc)

    @staticmethod
    def _ok(message: str, data: Dict) -> Dict:
        return {"success": True, "message": message, "data": data}

    @staticmethod
    def _fail(message: str, data: Optional[Dict] = None) -> Dict:
        return {"success": False, "message": message, "data": data or {}}


def asdict_safe(obj: Any) -> Dict:
    """
    将 dataclass 转换为 dict（避免循环导入 dataclasses.asdict 时的副作用）

    Args:
        obj: 任意 dataclass 实例

    Returns:
        字典表示
    """
    from dataclasses import asdict
    return asdict(obj)

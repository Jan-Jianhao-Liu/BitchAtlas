"""
BirchAtlas - 边缘网关模拟器
=============================

模拟边缘网关行为：
1. 生成合成的钢筋间距检测数据
2. 运行 BIRCH 流式聚类
3. 通过 MQTT 推送结果到 EMQX
4. 上报遥测数据
5. 模拟设备影子同步

使用方法：
    python main.py
    python main.py --mqtt-host localhost --mqtt-port 1883
    python main.py --mode demo  # 演示模式，更丰富的输出
"""

import argparse
import json
import sys
import os
import time
import random
import signal
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional

# 添加项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from edge.clustering import BirchTree, OutlierDetector, CFSerializer


class MockMQTTClient:
    """
    MQTT 客户端（模拟实现，无需真实 MQTT broker 即可运行）
    
    支持两种模式：
    1. mock 模式：在控制台打印消息
    2. real 模式：连接真实 MQTT broker
    """
    
    def __init__(self, host: str = 'localhost', port: int = 1883, 
                 use_mock: bool = True):
        self.host = host
        self.port = port
        self.use_mock = use_mock
        self.connected = False
        self.published_messages = []
        self._client = None
        
        if not use_mock:
            try:
                import paho.mqtt.client as mqtt
                self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                self._client.on_connect = self._on_connect
                self._client.on_publish = self._on_publish
            except ImportError:
                print("[WARN] paho-mqtt 未安装，使用 mock 模式")
                self.use_mock = True
    
    def connect(self) -> bool:
        """连接到 MQTT broker"""
        if self.use_mock:
            self.connected = True
            print(f"[MQTT] Mock 模式已激活 (host={self.host}:{self.port})")
            return True
        
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.loop_start()
            self.connected = True
            print(f"[MQTT] 已连接到 {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[MQTT] 连接失败: {e}")
            print("[MQTT] 切换到 mock 模式")
            self.use_mock = True
            self.connected = True
            return True
    
    def disconnect(self):
        """断开连接"""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
        self.connected = False
        print("[MQTT] 已断开")
    
    def publish(self, topic: str, payload: Dict, qos: int = 1):
        """发布消息"""
        message = json.dumps(payload, ensure_ascii=False)
        self.published_messages.append({
            'topic': topic,
            'payload': payload,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        if self.use_mock:
            print(f"[MQTT] >>> {topic}: {self._truncate(message, 120)}")
        else:
            try:
                self._client.publish(topic, message, qos=qos)
            except Exception as e:
                print(f"[MQTT] 发布失败: {e}")
    
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"[MQTT] 连接成功 (reason={reason_code})")
    
    def _on_publish(self, client, userdata, mid, reason_code, properties):
        pass
    
    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."


class RebarDataGenerator:
    """
    钢筋间距检测数据生成器
    
    生成符合 V1.0 协议的数据格式：
    - 底横筋: 300mm 左右
    - 底纵筋: 150mm 左右  
    - 面横筋: 250mm 左右
    - 面纵筋: 200mm 左右
    
    支持：
    - 正常数据生成
    - 模拟施工缺陷（异常间距）
    - 模拟测量误差
    """
    
    # 数据类型定义
    DATA_TYPES = {
        1: {'name': '底横筋', 'mean': 300.0, 'std': 5.0, 'count': 5},
        2: {'name': '底纵筋', 'mean': 150.0, 'std': 3.0, 'count': 8},
        3: {'name': '面横筋', 'mean': 250.0, 'std': 4.0, 'count': 6},
        4: {'name': '面纵筋', 'mean': 200.0, 'std': 3.5, 'count': 7}
    }
    
    def __init__(self, anomaly_probability: float = 0.1):
        self.anomaly_probability = anomaly_probability
    
    def generate_single_type(self, data_type: int) -> List[float]:
        """
        生成单一类型的钢筋间距数据
        
        Args:
            data_type: 数据类型 (1-4)
            
        Returns:
            间距值列表
        """
        config = self.DATA_TYPES[data_type]
        values = []
        
        for i in range(config['count']):
            if random.random() < self.anomaly_probability:
                # 生成异常值（间距过大或过小）
                anomaly_factor = random.choice([0.5, 1.5, 2.0])
                value = config['mean'] * anomaly_factor + np.random.normal(0, config['std'])
            else:
                # 正常值
                value = config['mean'] + np.random.normal(0, config['std'])
            
            values.append(round(value, 1))
        
        return values
    
    def generate_all_types(self, include_anomaly: bool = False) -> List[Dict]:
        """
        生成所有类型的检测数据
        
        Returns:
            数据列表 [{type, vals}]
        """
        result = []
        
        for data_type in range(1, 5):
            vals = self.generate_single_type(data_type)
            result.append({
                'type': data_type,
                'vals': vals
            })
        
        return result
    
    def generate_record(self, measure_point_id: int, dev_code: str, 
                        factor: float = 0.85, high: float = 3.2) -> Dict:
        """
        生成完整的检测记录（兼容 V1.0 格式）
        
        Args:
            measure_point_id: 测点ID
            dev_code: 采集仪编号
            factor: mm/px 比例
            high: 拍摄高度
            
        Returns:
            完整的检测记录
        """
        now = datetime.now(timezone.utc)
        
        # 生成图片 URL（模拟）
        img_base = f"https://oss.birchatlas.example.com/images/{now.strftime('%Y%m%d')}"
        
        record = {
            'id': str(measure_point_id),
            'dev_code': dev_code,
            'img1_w': 1920,
            'img1_h': 1080,
            'img2_w': 1920,
            'img2_h': 1080,
            'img3_w': 1920,
            'img3_h': 1080,
            'factor': factor,
            'high': high,
            'par1': 'auto',
            'par2': '',
            'par3': '',
            'url1': f"{img_base}/{dev_code}_raw.jpg",
            'url2': f"{img_base}/{dev_code}_detected.jpg",
            'url3': f"{img_base}/{dev_code}_floor.jpg",
            'record_time': now.isoformat(),
            'data_list': self.generate_all_types(),
            'source': 1  # 0=人工 1=算法
        }
        
        return record


class TelemetryGenerator:
    """
    遥测数据生成器
    
    模拟边缘网关的运行状态指标：
    - CPU/GPU 使用率和温度
    - 内存使用
    - 网络流量
    - 推理耗时
    - 聚类耗时
    """
    
    def generate(self, device_code: str, inference_ms: float = 150.0, 
                 cluster_ms: float = 5.0, total_points: int = 0) -> Dict:
        """
        生成遥测数据
        
        Args:
            device_code: 设备编号
            inference_ms: 最近推理耗时
            cluster_ms: 最近聚类耗时
            total_points: 已处理总点数
            
        Returns:
            遥测数据
        """
        return {
            'device_code': device_code,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'cpu': {
                'usage_percent': round(random.uniform(30, 85), 1),
                'temperature_celsius': round(random.uniform(45, 65), 1)
            },
            'gpu': {
                'usage_percent': round(random.uniform(40, 90), 1),
                'temperature_celsius': round(random.uniform(55, 75), 1),
                'memory_used_mb': random.randint(2000, 6000),
                'memory_total_mb': 8192
            },
            'memory': {
                'used_mb': random.randint(1500, 3500),
                'total_mb': 8192
            },
            'network': {
                'rx_mbps': round(random.uniform(1, 10), 2),
                'tx_mbps': round(random.uniform(0.5, 5), 2)
            },
            'inference': {
                'last_inference_ms': round(inference_ms, 1),
                'total_inferences': random.randint(1000, 100000),
                'avg_inference_ms': round(inference_ms * 0.95, 1)
            },
            'clustering': {
                'cf_tree_size': total_points,
                'last_cluster_ms': round(cluster_ms, 2),
                'total_points_processed': total_points,
                'total_outliers_detected': random.randint(0, 50)
            }
        }


class EdgeSimulator:
    """
    边缘网关模拟器主类
    
    整合数据生成、BIRCH 聚类、MQTT 通信等功能，
    模拟真实边缘网关的完整工作流程。
    """
    
    def __init__(self, 
                 mqtt_host: str = 'localhost',
                 mqtt_port: int = 1883,
                 use_mock_mqtt: bool = True,
                 gateway_code: str = 'GW-00000001',
                 measure_point_count: int = 3,
                 anomaly_probability: float = 0.1):
        """
        初始化模拟器
        
        Args:
            mqtt_host: MQTT broker 地址
            mqtt_port: MQTT broker 端口
            use_mock_mqtt: 是否使用 mock MQTT
            gateway_code: 网关编号
            measure_point_count: 测点数量
            anomaly_probability: 异常数据概率
        """
        self.gateway_code = gateway_code
        self.measure_point_count = measure_point_count
        
        # 初始化 MQTT 客户端
        self.mqtt_client = MockMQTTClient(
            host=mqtt_host, 
            port=mqtt_port,
            use_mock=use_mock_mqtt
        )
        
        # 为每个测点创建独立的 BIRCH 树和离群检测器
        self.clusterers: Dict[str, Dict] = {}
        self.data_generator = RebarDataGenerator(anomaly_probability)
        self.telemetry_generator = TelemetryGenerator()
        
        for mp_id in range(1, measure_point_count + 1):
            mp_key = f"MP-{mp_id:03d}"
            self.clusterers[mp_key] = {
                'birch_tree': BirchTree(radius_threshold=0.5),
                'detector': OutlierDetector(
                    threshold_k=2.5,
                    consecutive_limit=3,
                    min_points_for_detection=5
                ),
                'measure_point_id': mp_id,
                'stats': {
                    'total_records': 0,
                    'total_values': 0,
                    'outliers_found': 0,
                    'alerts_triggered': 0
                }
            }
        
        # 运行状态
        self.running = False
        self.record_count = 0
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """优雅关闭"""
        print("\n[EdgeSim] 收到停止信号，正在关闭...")
        self.stop()
    
    def start(self):
        """启动模拟器"""
        print("=" * 60)
        print("BirchAtlas 边缘网关模拟器")
        print("=" * 60)
        print(f"  网关编号: {self.gateway_code}")
        print(f"  测点数: {self.measure_point_count}")
        print(f"  MQTT: {self.mqtt_client.host}:{self.mqtt_client.port}")
        print(f"  模式: {'Mock' if self.mqtt_client.use_mock else 'Real'}")
        print("=" * 60)
        
        # 连接 MQTT
        self.mqtt_client.connect()
        
        self.running = True
        print("\n[EdgeSim] 模拟器已启动，按 Ctrl+C 停止\n")
    
    def stop(self):
        """停止模拟器"""
        self.running = False
        self.mqtt_client.disconnect()
        
        # 打印统计信息
        self._print_final_stats()
        print("\n[EdgeSim] 模拟器已停止")
    
    def run_detection_cycle(self, num_records: int = 10, interval_ms: int = 500):
        """
        运行检测循环
        
        Args:
            num_records: 检测记录数量
            interval_ms: 记录间隔（毫秒）
        """
        for i in range(num_records):
            if not self.running:
                break
            
            self._process_detection_cycle()
            self.record_count += 1
            
            if self.record_count % 10 == 0:
                self._print_progress()
            
            time.sleep(interval_ms / 1000.0)
    
    def _process_detection_cycle(self):
        """
        处理单个检测周期：
        1. 为每个测点生成数据
        2. 运行 BIRCH 聚类检测离群点
        3. 上报检测结果
        4. 上报 CF 树增量（每 10 条）
        5. 上报遥测数据
        """
        for mp_key, clusterer in self.clusterers.items():
            mp_id = clusterer['measure_point_id']
            dev_code = f"BB-{mp_id:08d}"
            
            # 生成检测记录
            record = self.data_generator.generate_record(
                measure_point_id=mp_id,
                dev_code=dev_code
            )
            
            # 处理每个数据类型的间距值
            for data_item in record['data_list']:
                data_type = data_item['type']
                vals = data_item['vals']
                
                # 运行离群检测
                detection_results = clusterer['detector'].detect_batch(vals)
                
                # 记录离群索引
                outlier_indices = []
                for idx, result in enumerate(detection_results):
                    if result['is_outlier']:
                        outlier_indices.append(idx)
                        clusterer['stats']['outliers_found'] += 1
                
                # 更新记录中的离群信息
                data_item['outlier_indices'] = outlier_indices
                
                # 更新 CF 树统计
                clusterer['stats']['total_values'] += len(vals)
            
            # 更新统计
            clusterer['stats']['total_records'] += 1
            
            # 上报检测数据
            self._report_detection_data(mp_key, record)
            
            # 每 10 条上报一次 CF 树状态
            if clusterer['stats']['total_records'] % 10 == 0:
                self._report_cf_tree_status(mp_key, clusterer)
            
            # 更新设备影子
            self._update_device_shadow(clusterer)
        
        # 上报遥测数据
        self._report_telemetry()
    
    def _report_detection_data(self, mp_key: str, record: Dict):
        """上报检测数据"""
        topic = f"{self.gateway_code}/data/upload"
        payload = {
            'record': record,
            'cluster_snapshot': self._get_cluster_snapshot(mp_key)
        }
        self.mqtt_client.publish(topic, payload)
    
    def _report_cf_tree_status(self, mp_key: str, clusterer: Dict):
        """上报 CF 树状态"""
        tree = clusterer['detector'].birch_tree
        data_type = 'mixed'
        
        # 简化：使用第一个数据类型
        tree_data = CFSerializer.to_json(
            tree, 
            self.gateway_code, 
            mp_key, 
            data_type
        )
        
        topic = f"{self.gateway_code}/cf/tree"
        self.mqtt_client.publish(topic, tree_data)
    
    def _get_cluster_snapshot(self, mp_key: str) -> Dict:
        """获取聚类快照"""
        clusterer = self.clusterers[mp_key]
        tree = clusterer['detector'].birch_tree
        return {
            'clusters': tree.get_clusters(),
            'stats': tree.get_stats()
        }
    
    def _update_device_shadow(self, clusterer: Dict):
        """更新设备影子"""
        topic = f"{self.gateway_code}/shadow/reported"
        shadow_state = {
            'status': 'online',
            'last_detection': datetime.now(timezone.utc).isoformat(),
            'total_records': str(clusterer['stats']['total_records']),
            'outliers_found': str(clusterer['stats']['outliers_found'])
        }
        self.mqtt_client.publish(topic, shadow_state)
    
    def _report_telemetry(self):
        """上报遥测数据"""
        topic = f"{self.gateway_code}/telemetry"
        
        # 获取最大统计值
        max_points = max(
            c['detector'].birch_tree.total_points_processed 
            for c in self.clusterers.values()
        )
        
        telemetry = self.telemetry_generator.generate(
            self.gateway_code,
            total_points=max_points
        )
        self.mqtt_client.publish(topic, telemetry, qos=0)
    
    def _print_progress(self):
        """打印进度"""
        print(f"\n[EdgeSim] ========== 进度更新 #{self.record_count} ==========")
        
        for mp_key, clusterer in self.clusterers.items():
            stats = clusterer['stats']
            tree_stats = clusterer['detector'].birch_tree.get_stats()
            
            print(f"  {mp_key} ({clusterer['measure_point_id']}):")
            print(f"    记录数: {stats['total_records']}")
            print(f"    检测值: {stats['total_values']}")
            print(f"    离群点: {stats['outliers_found']}")
            print(f"    当前簇数: {tree_stats['num_clusters']}")
            print(f"    CF 树点数: {tree_stats['total_points']}")
    
    def _print_final_stats(self):
        """打印最终统计"""
        print("\n" + "=" * 60)
        print("最终统计")
        print("=" * 60)
        
        total_outliers = 0
        for mp_key, clusterer in self.clusterers.items():
            stats = clusterer['stats']
            total_outliers += stats['outliers_found']
            print(f"  {mp_key}: {stats['total_records']} 条记录, "
                  f"{stats['total_values']} 个检测值, "
                  f"{stats['outliers_found']} 个离群点")
        
        print(f"\n  总计: {self.record_count} 条记录, {total_outliers} 个离群点")
        print(f"  MQTT 消息数: {len(self.mqtt_client.published_messages)}")
    
    def run_demo_mode(self, duration_seconds: int = 30):
        """
        演示模式：持续运行指定时间
        
        Args:
            duration_seconds: 运行时长（秒）
        """
        self.start()
        
        print(f"\n[EdgeSim] 演示模式运行 {duration_seconds} 秒...\n")
        
        try:
            start_time = time.time()
            interval = 0.5  # 500ms
            
            while self.running and (time.time() - start_time) < duration_seconds:
                self._process_detection_cycle()
                self.record_count += 1
                
                if self.record_count % 20 == 0:
                    self._print_progress()
                
                time.sleep(interval)
            
            print(f"\n[EdgeSim] 演示完成，共处理 {self.record_count} 个检测周期")
            
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def main():
    parser = argparse.ArgumentParser(
        description='BirchAtlas 边缘网关模拟器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 启动演示模式（30秒）
  python main.py --mode demo --duration 30
  
  # 连接真实 MQTT broker
  python main.py --mqtt-host localhost --mqtt-port 1883
  
  # 长时间运行
  python main.py --count 1000 --interval 100
        """
    )
    
    parser.add_argument('--mqtt-host', default='localhost', 
                       help='MQTT broker 地址 (默认: localhost)')
    parser.add_argument('--mqtt-port', type=int, default=1883,
                       help='MQTT broker 端口 (默认: 1883)')
    parser.add_argument('--use-mock', action='store_true',
                       help='使用 mock MQTT（不发送真实消息）')
    parser.add_argument('--gateway-code', default='GW-00000001',
                       help='网关编号 (默认: GW-00000001)')
    parser.add_argument('--measure-points', type=int, default=3,
                       help='测点数量 (默认: 3)')
    parser.add_argument('--anomaly-rate', type=float, default=0.1,
                       help='异常数据概率 (默认: 0.1)')
    parser.add_argument('--mode', choices=['demo', 'batch', 'continuous'],
                       default='demo', help='运行模式 (默认: demo)')
    parser.add_argument('--duration', type=int, default=30,
                       help='演示模式运行时长（秒，默认: 30）')
    parser.add_argument('--count', type=int, default=100,
                       help='批量模式记录数量 (默认: 100)')
    parser.add_argument('--interval', type=int, default=500,
                       help='记录间隔毫秒数 (默认: 500)')
    
    args = parser.parse_args()
    
    # 创建模拟器
    sim = EdgeSimulator(
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        use_mock_mqtt=args.use_mock,
        gateway_code=args.gateway_code,
        measure_point_count=args.measure_points,
        anomaly_probability=args.anomaly_rate
    )
    
    if args.mode == 'demo':
        sim.run_demo_mode(duration_seconds=args.duration)
    elif args.mode == 'batch':
        sim.start()
        sim.run_detection_cycle(
            num_records=args.count,
            interval_ms=args.interval
        )
        sim.stop()
    elif args.mode == 'continuous':
        sim.start()
        try:
            while True:
                sim.run_detection_cycle(num_records=10, interval_ms=args.interval)
        except KeyboardInterrupt:
            sim.stop()


if __name__ == '__main__':
    main()
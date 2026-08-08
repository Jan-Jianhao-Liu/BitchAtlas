"""
BirchAtlas 端到端流程验证脚本
================================

模拟 ingest-svc 和 cluster-svc 的完整交互流程：
1. 边缘设备生成钢筋间距检测数据（含异常值）
2. ingest-svc：接收数据 → z-score 离群检测 → 存储到 SQLite
3. cluster-svc：查询数据 → K-Means/层次/DBSCAN 聚类 → 质量评估
4. 多网关 CF 树合并 → 全局聚类

运行：python examples/e2e_demo.py
"""

import json
import logging
import os
import sys
import sqlite3
import time
import random
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# 添加项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from edge.clustering import (
    BirchTree, OutlierDetector, CFSerializer, ClusteringQuality
)

# ============================================================
# Logger 配置
# ============================================================
logger = logging.getLogger("birchatlas.e2e")


# ============================================================
# 1. 数据生成器（模拟边缘设备）
# ============================================================

class RebarDataGenerator:
    """钢筋间距检测数据生成器"""

    DATA_TYPES = {
        1: {'name': '底横筋', 'mean': 300.0, 'std': 5.0, 'count': 5},
        2: {'name': '底纵筋', 'mean': 150.0, 'std': 3.0, 'count': 8},
        3: {'name': '面横筋', 'mean': 250.0, 'std': 4.0, 'count': 6},
        4: {'name': '面纵筋', 'mean': 200.0, 'std': 3.5, 'count': 7},
    }

    def __init__(self, anomaly_probability: float = 0.08, seed: int = 42):
        self.rng = np.random.RandomState(seed)
        self.anomaly_probability = anomaly_probability

    def generate_vals(self, data_type: int, inject_anomaly: bool = False) -> List[float]:
        """生成单类型间距数据"""
        cfg = self.DATA_TYPES[data_type]
        vals = []
        for _ in range(cfg['count']):
            if inject_anomaly and self.rng.random() < self.anomaly_probability:
                # 异常值：间距过大或过小
                factor = self.rng.choice([0.5, 0.6, 1.5, 1.8])
                val = cfg['mean'] * factor + self.rng.normal(0, cfg['std'])
            else:
                val = cfg['mean'] + self.rng.normal(0, cfg['std'])
            vals.append(round(val, 1))
        return vals

    def generate_record(self, dev_code: str, mp_id: int,
                        inject_anomaly: bool = False) -> Dict:
        """生成完整检测记录"""
        now = datetime.now(timezone.utc)
        return {
            'id': str(mp_id),
            'dev_code': dev_code,
            'factor': 0.85,
            'high': 3.2,
            'url1': f"https://oss.example.com/{dev_code}_raw.jpg",
            'record_time': now.isoformat(),
            'data_list': [
                {'type': dt, 'vals': self.generate_vals(dt, inject_anomaly)}
                for dt in range(1, 5)
            ],
            'source': 1,
        }


# ============================================================
# 2. ingest-svc 模拟（z-score 离群检测 + SQLite 存储）
# ============================================================

class IngestService:
    """模拟 ingest-svc：接收数据、离群检测、存储"""

    def __init__(self, db_path: str = "./data/e2e_demo.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # 删除旧数据库
        if os.path.exists(db_path):
            os.remove(db_path)

        self.conn = sqlite3.connect(db_path)
        self._init_db()
        self.record_count = 0
        self.total_outliers = 0
        logger.info("IngestService 初始化完成, db_path=%s", db_path)

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS detect_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT NOT NULL,
                dev_code TEXT,
                measure_point_id INTEGER,
                factor REAL,
                data_type INTEGER,
                vals TEXT,
                outlier_indices TEXT,
                outlier_details TEXT,
                quality_grade TEXT DEFAULT 'A',
                record_time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dev_code ON detect_data(dev_code)"
        )
        self.conn.commit()

    def upload(self, record: Dict) -> Dict:
        """模拟 POST /api/v1/upload/algorithm"""
        self.record_count += 1
        record_id = f"rec_{int(time.time()*1000000)}_{self.record_count}"
        all_outliers = []

        logger.info("[ingest] 收到上传请求 record_id=%s dev_code=%s mp_id=%s data_types=%s",
                     record_id, record['dev_code'], record['id'],
                     [item['type'] for item in record['data_list']])

        for item in record['data_list']:
            vals = item['vals']
            data_type = item['type']
            type_name = RebarDataGenerator.DATA_TYPES.get(data_type, {}).get('name', f'type_{data_type}')

            logger.info("[ingest] 处理 data_type=%d(%s) vals=%s", data_type, type_name, vals)

            # z-score 离群检测（与 ingest-svc Go 代码一致）
            outliers = self._detect_outliers_zscore(vals)

            if outliers:
                logger.info("[ingest] 离群检测命中 data_type=%d(%s) outliers=%d 详情=%s",
                            data_type, type_name, len(outliers),
                            [{"index": o['index'], "value": o['value'],
                              "z": o['z_score'], "mean": o['expected_mean']} for o in outliers])
            else:
                logger.info("[ingest] 离群检测未命中 data_type=%d(%s) vals_count=%d",
                            data_type, type_name, len(vals))

            # 存入数据库
            self.conn.execute("""
                INSERT INTO detect_data
                (record_id, dev_code, measure_point_id, factor, data_type,
                 vals, outlier_indices, outlier_details, quality_grade, record_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id, record['dev_code'], int(record['id']),
                record['factor'], data_type,
                json.dumps(vals),
                json.dumps([o['index'] for o in outliers]),
                json.dumps(outliers),
                'C' if len(outliers) > 0 else 'A',
                record['record_time'],
            ))
            logger.info("[ingest] 数据已存储 record_id=%s data_type=%d quality_grade=%s",
                        record_id, data_type, 'C' if len(outliers) > 0 else 'A')

            all_outliers.extend(outliers)

        self.conn.commit()
        self.total_outliers += len(all_outliers)

        logger.info("[ingest] 上传完成 record_id=%s total_outliers=%d cumulative=%d",
                     record_id, len(all_outliers), self.total_outliers)

        return {
            'record_id': record_id,
            'outlier_count': len(all_outliers),
            'outliers': all_outliers,
        }

    def _detect_outliers_zscore(self, vals: List[float], threshold: float = 2.5) -> List[Dict]:
        """z-score 离群检测（复刻 ingest-svc 的 Go 逻辑）"""
        if len(vals) < 5:
            logger.info("[ingest] z-score 跳过: vals数量=%d < 5", len(vals))
            return []

        n = len(vals)
        mean = sum(vals) / n
        var = sum(v * v for v in vals) / n - mean * mean
        std = var ** 0.5 if var > 0 else 0

        logger.info("[ingest] z-score 统计 n=%d mean=%.2f std=%.4f threshold=%.1f", n, mean, std, threshold)

        if std < 0.01:
            logger.info("[ingest] z-score 跳过: std=%.4f < 0.01 (数据无波动)", std)
            return []

        outliers = []
        for i, v in enumerate(vals):
            z = (v - mean) / std
            if abs(z) > threshold:
                outliers.append({
                    'index': i,
                    'value': v,
                    'expected_mean': round(mean, 2),
                    'z_score': round(z, 2),
                    'data_type': None,  # 填充在外部
                })
        return outliers

    def query_all(self) -> List[Dict]:
        """查询所有数据（模拟 cluster-svc 拉取数据）"""
        cursor = self.conn.execute("""
            SELECT dev_code, measure_point_id, data_type, vals, outlier_indices
            FROM detect_data ORDER BY id
        """)
        records = []
        for row in cursor:
            records.append({
                'dev_code': row[0],
                'measure_point_id': row[1],
                'data_type': row[2],
                'vals': json.loads(row[3]),
                'outlier_indices': json.loads(row[4]),
            })
        return records

    def query_by_type(self, data_type: int) -> List[float]:
        """按类型查询所有间距值"""
        cursor = self.conn.execute(
            "SELECT vals FROM detect_data WHERE data_type = ? ORDER BY id",
            (data_type,)
        )
        all_vals = []
        for row in cursor:
            all_vals.extend(json.loads(row[0]))
        return all_vals

    def close(self):
        self.conn.close()


# ============================================================
# 3. cluster-svc 模拟（K-Means/层次/DBSCAN + CF 树合并）
# ============================================================

class ClusterService:
    """模拟 cluster-svc：聚类分析 + CF 树合并"""

    def __init__(self):
        self.jobs = {}

    def create_kmeans_job(self, data: List[List[float]], k: int) -> Dict:
        """模拟 POST /api/v1/cluster/jobs (kmeans)"""
        from sklearn.cluster import KMeans as SKKMeans
        data_arr = np.array(data)

        if len(data_arr) < k:
            k = max(1, len(data_arr))
            logger.info("[cluster] K-Means 调整 k=%d (原始数据量=%d 不足)", k, len(data_arr))

        logger.info("[cluster] K-Means 开始 n_samples=%d n_features=%d k=%d",
                     len(data_arr), data_arr.shape[1] if data_arr.ndim > 1 else 1, k)

        km = SKKMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(data_arr)

        logger.info("[cluster] K-Means 完成 centroids=%s",
                     [round(c[0], 2) for c in km.cluster_centers_.tolist()])

        # 评估
        evaluation = self._evaluate(data_arr, labels)

        return {
            'job_id': f"cj_{int(time.time()*1000000)}",
            'algorithm': 'kmeans',
            'status': 'completed',
            'labels': labels.tolist(),
            'centroids': km.cluster_centers_.tolist(),
            'evaluation': evaluation,
        }

    def create_dbscan_job(self, data: List[List[float]], eps: float, min_pts: int) -> Dict:
        """模拟 POST /api/v1/cluster/jobs (dbscan)"""
        from sklearn.cluster import DBSCAN
        data_arr = np.array(data)

        logger.info("[cluster] DBSCAN 开始 n_samples=%d eps=%.2f min_pts=%d",
                     len(data_arr), eps, min_pts)

        db = DBSCAN(eps=eps, min_samples=min_pts)
        labels = db.fit_predict(data_arr)

        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_noise = list(labels).count(-1)
        logger.info("[cluster] DBSCAN 完成 n_clusters=%d n_noise=%d", n_clusters, n_noise)

        evaluation = self._evaluate(data_arr, labels)

        return {
            'job_id': f"cj_{int(time.time()*1000000)}",
            'algorithm': 'dbscan',
            'status': 'completed',
            'labels': labels.tolist(),
            'n_clusters': n_clusters,
            'n_noise': n_noise,
            'evaluation': evaluation,
        }

    def merge_cf_trees(self, trees: List[Dict]) -> Dict:
        """模拟 POST /api/v1/cluster/cf/merge"""
        # 收集所有 CF 质心
        all_centroids = []
        all_n = []
        gateway_map = []

        logger.info("[cluster] CF 树合并开始, 输入树数量=%d", len(trees))

        for tree_data in trees:
            gw = tree_data.get('gateway_code', 'unknown')
            cf_count = len(tree_data.get('centroids', []))
            logger.info("[cluster]   网关=%s 叶CF数=%d", gw, cf_count)
            for cf in tree_data.get('centroids', []):
                all_centroids.append(cf['centroid'])
                all_n.append(cf['n'])
                gateway_map.append(gw)

        if not all_centroids:
            logger.info("[cluster] CF 树合并: 无质心数据，返回空结果")
            return {'total_clusters': 0, 'clusters': []}

        logger.info("[cluster] CF 树合并: 总质心数=%d, 开始 K-Means 聚类", len(all_centroids))

        # K-Means 聚类合并
        k = min(4, len(all_centroids))
        result = self.create_kmeans_job(all_centroids, k)

        clusters = []
        for i in range(k):
            mask = [j for j, l in enumerate(result['labels']) if l == i]
            cluster = {
                'cluster_id': i + 1,
                'centroid': result['centroids'][i],
                'point_count': sum(all_n[j] for j in mask),
                'member_gateways': list(set(gateway_map[j] for j in mask)),
            }
            clusters.append(cluster)
            logger.info("[cluster]   合并簇%d: 质心=%.2f 点数=%d 网关=%s",
                        cluster['cluster_id'], cluster['centroid'][0],
                        cluster['point_count'], cluster['member_gateways'])

        logger.info("[cluster] CF 树合并完成, 总簇数=%d", len(clusters))

        return {
            'merge_id': f"merge_{int(time.time()*1000000)}",
            'total_clusters': len(clusters),
            'clusters': clusters,
        }

    def _evaluate(self, data: np.ndarray, labels: np.ndarray) -> Dict:
        """聚类质量评估"""
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        n_points = len(data)

        logger.info("[cluster] 质量评估 n_points=%d n_clusters=%d", n_points, n_clusters)

        if n_clusters < 2 or n_clusters >= n_points:
            logger.info("[cluster] 质量评估跳过: n_clusters=%d 不满足条件 (需 2<=k<n_points)", n_clusters)
            return {
                'silhouette': 0.0,
                'n_clusters': n_clusters,
                'n_points': n_points,
                'note': '聚类数不足，无法计算轮廓系数'
            }

        from sklearn.metrics import silhouette_score, davies_bouldin_score, calinski_harabasz_score

        # 过滤噪声点
        mask = labels >= 0
        if mask.sum() < n_clusters:
            logger.info("[cluster] 质量评估跳过: 有效点=%d < n_clusters=%d", mask.sum(), n_clusters)
            return {
                'silhouette': 0.0,
                'n_clusters': n_clusters,
                'n_points': n_points,
                'note': '有效点数不足'
            }

        sil = silhouette_score(data[mask], labels[mask])
        dbi = davies_bouldin_score(data[mask], labels[mask])
        ch = calinski_harabasz_score(data[mask], labels[mask])

        logger.info("[cluster] 质量评估完成 silhouette=%.4f davies_bouldin=%.4f calinski_harabasz=%.2f",
                     sil, dbi, ch)

        return {
            'silhouette': round(sil, 4),
            'davies_bouldin': round(dbi, 4),
            'calinski_harabasz': round(ch, 2),
            'n_clusters': n_clusters,
            'n_points': n_points,
        }


# ============================================================
# 4. 边缘 BIRCH 聚类模拟（模拟 edge-gateway 行为）
# ============================================================

class EdgeBirchProcessor:
    """边缘 BIRCH 流式聚类处理器（模拟 edge-gateway）"""

    def __init__(self, gateway_code: str):
        self.gateway_code = gateway_code
        # 每种数据类型独立的 BIRCH 树 + 离群检测器
        self.trees: Dict[int, BirchTree] = {}
        self.detectors: Dict[int, OutlierDetector] = {}
        self.stats: Dict[int, Dict] = {}

        logger.info("[edge] 初始化 BIRCH 处理器 gateway=%s", gateway_code)

        for dt in range(1, 5):
            self.trees[dt] = BirchTree(radius_threshold=5.0)
            self.detectors[dt] = OutlierDetector(
                birch_tree=self.trees[dt],
                threshold_k=3.0,
                consecutive_limit=3,
                min_points_for_detection=10,
                min_baseline_cf_points=3,
            )
            self.stats[dt] = {
                'total_vals': 0,
                'outliers': 0,
                'alerts': 0,
            }
            name = RebarDataGenerator.DATA_TYPES[dt]['name']
            logger.info("[edge]   data_type=%d(%s) BIRCH树已创建 radius_threshold=5.0 "
                        "threshold_k=3.0 consecutive_limit=3 min_baseline_cf_points=3",
                        dt, name)

    def process_record(self, record: Dict) -> Dict:
        """处理一条检测记录"""
        dev_code = record.get('dev_code', 'unknown')
        mp_id = record.get('id', '?')
        logger.info("[edge] %s 处理记录 dev_code=%s mp_id=%s data_types=%s",
                     self.gateway_code, dev_code, mp_id,
                     [item['type'] for item in record['data_list']])

        results = {}
        for item in record['data_list']:
            dt = item['type']
            vals = item['vals']
            type_name = RebarDataGenerator.DATA_TYPES.get(dt, {}).get('name', f'type_{dt}')

            logger.info("[edge] %s 检测 data_type=%d(%s) vals=%s",
                         self.gateway_code, dt, type_name, vals)

            dt_results = []
            for v in vals:
                r = self.detectors[dt].detect(v)
                dt_results.append({
                    'value': v,
                    'is_outlier': r['is_outlier'],
                    'z_score': r.get('z_score'),
                    'suggestion': r['suggestion'],
                    'alert': r['alert_triggered'],
                })
                self.stats[dt]['total_vals'] += 1

                if r['is_outlier']:
                    self.stats[dt]['outliers'] += 1
                    logger.info("[edge] %s 离群命中 data_type=%d(%s) value=%.1f z_score=%.2f "
                                "suggestion=%s consecutive_outliers=%d",
                                self.gateway_code, dt, type_name, v,
                                r.get('z_score', 0), r['suggestion'],
                                self.detectors[dt].consecutive_outliers)

                if r['alert_triggered']:
                    self.stats[dt]['alerts'] += 1
                    logger.info("[edge] %s 告警触发! data_type=%d(%s) value=%.1f "
                                "连续离群达上限=%d",
                                self.gateway_code, dt, type_name, v,
                                self.detectors[dt].consecutive_limit)

            # 记录该类型的 CF 树当前状态
            tree_stats = self.trees[dt].get_stats()
            logger.info("[edge] %s data_type=%d(%s) 处理完成 CF树状态: clusters=%d "
                        "total_points=%d outliers=%d",
                        self.gateway_code, dt, type_name,
                        tree_stats['num_clusters'], tree_stats['total_points'],
                        tree_stats['outlier_count'])

            results[dt] = dt_results

        return results

    def get_cf_tree_data(self, data_type: int) -> Dict:
        """获取 CF 树序列化数据"""
        tree = self.trees[data_type]
        stats = tree.get_stats()
        logger.info("[edge] %s 序列化 CF 树 data_type=%d clusters=%d total_points=%d",
                     self.gateway_code, data_type,
                     stats['num_clusters'], stats['total_points'])

        data = CFSerializer.to_json(
            tree,
            self.gateway_code,
            f"MP-{data_type:03d}",
            f"type_{data_type}"
        )

        logger.info("[edge] %s CF 树序列化完成 leaf_cfs=%d",
                     self.gateway_code, len(data.get('centroids', [])))
        return data

    def get_summary(self) -> Dict:
        """获取统计摘要"""
        summary = {}
        for dt in range(1, 5):
            tree = self.trees[dt]
            stats = tree.get_stats()
            summary[dt] = {
                'name': RebarDataGenerator.DATA_TYPES[dt]['name'],
                'total_vals': self.stats[dt]['total_vals'],
                'outliers': self.stats[dt]['outliers'],
                'alerts': self.stats[dt]['alerts'],
                'clusters': stats['num_clusters'],
                'cf_tree_points': stats['total_points'],
            }
        return summary


# ============================================================
# 5. 主流程
# ============================================================

def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_subheader(title: str):
    print(f"\n  --- {title} ---")


def main():
    # 配置 logging：控制台输出 + 文件输出
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("./data/e2e_demo.log", encoding="utf-8"),
        ],
    )

    random.seed(42)
    np.random.seed(42)

    logger.info("========== BirchAtlas 端到端流程验证启动 ==========")
    logger.info("随机种子: 42, 异常概率: 0.12")
    logger.info("流程: 边缘生成数据 → ingest-svc 存储 → cluster-svc 聚类 → CF 树合并")

    print_header("BirchAtlas 端到端流程验证")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  流程: 边缘生成数据 → ingest-svc 存储 → cluster-svc 聚类 → CF 树合并")
    print(f"  日志文件: ./data/e2e_demo.log")

    # ========================================
    # 阶段 1: 边缘数据生成 + ingest-svc 存储
    # ========================================
    print_header("阶段 1: 模拟边缘数据上传 → ingest-svc")

    generator = RebarDataGenerator(anomaly_probability=0.12, seed=42)
    ingest = IngestService()

    # 模拟 3 个网关，每个网关 5 个测点，每测点 10 条记录
    gateways = ['GW-00000001', 'GW-00000002', 'GW-00000003']
    total_records = 0
    total_outliers_ingest = 0

    logger.info("阶段1开始: 模拟 %d 个网关, 每网关 5 测点 × 10 条记录", len(gateways))

    for gw_code in gateways:
        print_subheader(f"网关 {gw_code} 上传数据")
        logger.info("阶段1: 网关 %s 开始上传数据", gw_code)
        for mp_id in range(1, 6):
            for _ in range(10):
                dev_code = f"BB-{gw_code[-8:]}-{mp_id:02d}"
                # 前 30 条正常，后面注入异常
                inject = total_records > 30
                record = generator.generate_record(dev_code, mp_id, inject_anomaly=inject)
                result = ingest.upload(record)
                total_records += 1
                total_outliers_ingest += result['outlier_count']

                if result['outlier_count'] > 0:
                    for o in result['outliers']:
                        print(f"    [离群] 测点{mp_id} 值={o['value']:.1f}mm "
                              f"z={o['z_score']:.2f} 均值={o['expected_mean']:.1f}mm")

    print(f"\n  ingest-svc 汇总:")
    print(f"    总记录数: {total_records}")
    print(f"    总离群值: {total_outliers_ingest}")
    logger.info("阶段1完成: 总记录=%d 总离群=%d", total_records, total_outliers_ingest)

    # ========================================
    # 阶段 2: 边缘 BIRCH 实时离群检测
    # ========================================
    print_header("阶段 2: 边缘 BIRCH 实时离群检测")
    logger.info("阶段2开始: 边缘 BIRCH 实时离群检测, %d 个网关", len(gateways))

    # 为每个网关创建 BIRCH 处理器
    edge_processors = {gw: EdgeBirchProcessor(gw) for gw in gateways}

    # 重新生成数据，让边缘处理器实时处理
    generator2 = RebarDataGenerator(anomaly_probability=0.12, seed=100)
    record_idx = 0

    for gw_code in gateways:
        print_subheader(f"网关 {gw_code} 实时检测")
        processor = edge_processors[gw_code]

        for mp_id in range(1, 6):
            for _ in range(10):
                dev_code = f"BB-{gw_code[-8:]}-{mp_id:02d}"
                inject = record_idx > 30
                record = generator2.generate_record(dev_code, mp_id, inject_anomaly=inject)
                results = processor.process_record(record)
                record_idx += 1

                # 打印离群检测详情
                for dt, dt_results in results.items():
                    for r in dt_results:
                        if r['is_outlier']:
                            name = RebarDataGenerator.DATA_TYPES[dt]['name']
                            print(f"    [BIRCH离群] {name} 值={r['value']:.1f}mm "
                                  f"z={r['z_score']:.2f} 建议={r['suggestion']}"
                                  f"{' [告警!]' if r['alert'] else ''}")

        # 打印网关统计
        summary = processor.get_summary()
        print(f"\n  {gw_code} BIRCH 统计:")
        for dt, s in summary.items():
            print(f"    {s['name']}: {s['total_vals']}个值, "
                  f"{s['outliers']}个离群, {s['clusters']}个簇, "
                  f"CF树{s['cf_tree_points']}点")

    # ========================================
    # 阶段 3: cluster-svc 聚类分析
    # ========================================
    print_header("阶段 3: cluster-svc 聚类分析")
    logger.info("阶段3开始: cluster-svc 聚类分析")

    cluster_svc = ClusterService()

    # 按数据类型从 ingest-svc 拉取数据
    for dt in range(1, 5):
        name = RebarDataGenerator.DATA_TYPES[dt]['name']
        vals = ingest.query_by_type(dt)

        if not vals:
            continue

        # 转换为二维数组（单特征）
        data = [[v] for v in vals]

        print_subheader(f"{name} (data_type={dt}) - {len(vals)}个值")

        # K-Means 聚类
        k = min(3, len(data))
        kmeans_result = cluster_svc.create_kmeans_job(data, k)
        print(f"    K-Means (k={k}):")
        print(f"      轮廓系数: {kmeans_result['evaluation']['silhouette']}")
        n_clusters_km = kmeans_result['evaluation'].get('n_clusters', k)
        print(f"      簇数: {n_clusters_km}")
        for i, c in enumerate(kmeans_result['centroids']):
            print(f"      簇{i+1} 质心: {c[0]:.2f}mm")

        # DBSCAN 聚类
        dbscan_result = cluster_svc.create_dbscan_job(data, eps=15.0, min_pts=5)
        print(f"    DBSCAN (eps=15, min_pts=5):")
        print(f"      簇数: {dbscan_result.get('n_clusters', 0)}")
        print(f"      噪声点: {dbscan_result.get('n_noise', 0)}")
        print(f"      轮廓系数: {dbscan_result['evaluation']['silhouette']}")

    # ========================================
    # 阶段 4: 多网关 CF 树合并
    # ========================================
    print_header("阶段 4: 多网关 CF 树合并 → 全局聚类")
    logger.info("阶段4开始: 多网关 CF 树合并")

    # 收集各网关底横筋(type=1)的 CF 树
    cf_trees = []
    for gw_code in gateways:
        tree_data = edge_processors[gw_code].get_cf_tree_data(data_type=1)
        cf_trees.append(tree_data)
        n_cfs = len(tree_data.get('centroids', []))
        total_pts = tree_data.get('stats', {}).get('total_points', 0)
        print(f"  {gw_code} 底横筋 CF 树: {n_cfs}个叶CF, {total_pts}个点")

    # 合并
    merge_result = cluster_svc.merge_cf_trees(cf_trees)

    print_subheader("合并结果")
    print(f"  全局簇数: {merge_result['total_clusters']}")
    for c in merge_result['clusters']:
        print(f"    簇{c['cluster_id']}: 质心={c['centroid'][0]:.2f}mm, "
              f"点数={c['point_count']}, 网关={c['member_gateways']}")

    # ========================================
    # 阶段 5: 汇总报告
    # ========================================
    print_header("验证结果汇总")
    logger.info("阶段5: 汇总报告")

    # ingest-svc 离群检测
    print(f"  [ingest-svc] z-score 离群检测:")
    print(f"    总记录: {total_records}")
    print(f"    检出离群: {total_outliers_ingest} 个")

    # 边缘 BIRCH 离群检测
    total_birch_outliers = 0
    total_birch_alerts = 0
    for gw_code in gateways:
        summary = edge_processors[gw_code].get_summary()
        for dt, s in summary.items():
            total_birch_outliers += s['outliers']
            total_birch_alerts += s['alerts']

    print(f"\n  [edge-gateway] BIRCH 实时离群检测:")
    print(f"    总检测值: {sum(s['total_vals'] for p in edge_processors.values() for s in p.get_summary().values())}")
    print(f"    检出离群: {total_birch_outliers} 个")
    print(f"    触发告警: {total_birch_alerts} 次")

    # cluster-svc 聚类
    print(f"\n  [cluster-svc] 聚类分析:")
    for dt in range(1, 5):
        vals = ingest.query_by_type(dt)
        if vals:
            data = [[v] for v in vals]
            result = cluster_svc.create_kmeans_job(data, min(3, len(data)))
            ev = result['evaluation']
            name = RebarDataGenerator.DATA_TYPES[dt]['name']
            print(f"    {name}: {len(vals)}个值 → {ev.get('n_clusters', 0)}个簇 "
                  f"(轮廓={ev['silhouette']})")

    # CF 树合并
    print(f"\n  [cluster-svc] CF 树合并:")
    print(f"    {len(gateways)}个网关 → {merge_result['total_clusters']}个全局簇")

    # 结论
    print(f"\n  {'✓ 离群检测逻辑验证通过' if total_outliers_ingest > 0 and total_birch_outliers > 0 else '✗ 离群检测未生效'}")
    print(f"  {'✓ 聚类分析验证通过' if merge_result['total_clusters'] > 0 else '✗ 聚类分析失败'}")
    print(f"  {'✓ CF 树合并验证通过' if merge_result['total_clusters'] >= 1 else '✗ CF 树合并失败'}")

    ingest.close()
    logger.info("========== 端到端流程验证完成 ==========")
    print(f"\n{'='*60}")
    print(f"  端到端流程验证完成")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()

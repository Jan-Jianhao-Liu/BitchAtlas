"""
离群检测器

基于 BIRCH CF 树的实时离群点检测：
1. 与最近 CF 簇心距离 > k·σ → 标记为离群候选
2. 连续 N 次离群 → 触发告警
3. 支持 z-score 计算和趋势分析
"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from .birch_tree import BirchTree


class OutlierDetector:
    """
    离群点检测器
    
    使用 BIRCH CF 树进行在线流式离群检测：
    - 每个新测量值与最近 CF 簇心比较
    - 如果距离超过阈值，标记为离群
    - 支持连续离群告警和趋势异常检测
    
    支持的检测模式：
    1. 静态阈值模式：固定上下限
    2. 统计模式：基于 CF 树的统计特征
    3. 趋势模式：检测突变和漂移
    """
    
    def __init__(self, 
                 birch_tree: Optional[BirchTree] = None,
                 threshold_k: float = 3.0,
                 consecutive_limit: int = 3,
                 min_points_for_detection: int = 10,
                 min_baseline_cf_points: int = 2):
        """
        初始化离群检测器
        
        Args:
            birch_tree: 关联的 BIRCH 树（可选）
            threshold_k: k·σ 倍数阈值
            consecutive_limit: 连续离群触发告警次数
            min_points_for_detection: 开始检测所需的最少数据点
            min_baseline_cf_points: CF 作为基线所需的最少点数
                （单个离群点形成的 CF 不会被用作基线）
        """
        self.birch_tree = birch_tree if birch_tree is not None else BirchTree()
        self.threshold_k = threshold_k
        self.consecutive_limit = consecutive_limit
        self.min_points_for_detection = min_points_for_detection
        self.min_baseline_cf_points = min_baseline_cf_points
        
        # 状态
        self.consecutive_outliers = 0
        self.detection_history: List[Dict] = []
        self.alert_history: List[Dict] = []
        
        # 统计信息
        self.total_detections = 0
        self.total_outliers = 0
        self.total_alerts = 0
    
    def detect(self, value: float, 
               point_id: Optional[str] = None,
               metadata: Optional[Dict] = None) -> Dict:
        """
        检测单个测量值
        
        Args:
            value: 测量值
            point_id: 测点ID
            metadata: 附加元数据
            
        Returns:
            检测结果
        """
        self.total_detections += 1
        
        result = {
            'value': value,
            'point_id': point_id,
            'is_outlier': False,
            'distance_to_nearest_cf': None,
            'z_score': None,
            'suggestion': 'accept',  # accept/flag/reject
            'alert_triggered': False,
            'metadata': metadata or {}
        }
        
        # CF 树数据不足时使用统计方法
        if self.birch_tree.total_points_processed < self.min_points_for_detection:
            # 使用历史统计
            stats_result = self._detect_from_statistics(value)
            result.update(stats_result)
        else:
            # 使用 CF 树检测
            cf_result = self._detect_from_cf_tree(value)
            result.update(cf_result)
        
        # 处理结果
        if result['is_outlier']:
            self.total_outliers += 1
            self.consecutive_outliers += 1
            result['suggestion'] = 'reject'
            
            # 连续离群检测
            if self.consecutive_outliers >= self.consecutive_limit:
                result['alert_triggered'] = True
                result['suggestion'] = 'flag'
                self.total_alerts += 1
                
                # 记录告警
                self.alert_history.append({
                    'timestamp': len(self.alert_history),
                    'consecutive_count': self.consecutive_outliers,
                    'last_value': value,
                    'point_id': point_id
                })
        else:
            self.consecutive_outliers = 0
            result['suggestion'] = 'accept'
        
        # 所有值都插入 CF 树（允许树学习新模式）
        self.birch_tree.insert(value)
        
        # 记录历史
        self.detection_history.append(result)
        
        return result
    
    def detect_batch(self, values: List[float],
                     point_ids: Optional[List[str]] = None) -> List[Dict]:
        """
        批量检测
        
        Args:
            values: 测量值列表
            point_ids: 测点ID列表（可选）
            
        Returns:
            检测结果列表
        """
        results = []
        for i, value in enumerate(values):
            point_id = point_ids[i] if point_ids else None
            result = self.detect(value, point_id)
            results.append(result)
        return results
    
    def _detect_from_statistics(self, value: float) -> Dict:
        """
        使用历史统计检测（CF 树数据不足时）
        """
        # 使用 BIRCH 树的最近值作为历史
        leaf_cfs = self.birch_tree.root.get_all_leaf_cfs()
        
        # 只使用点数足够的 CF 作为基线
        baseline_cfs = [cf for cf in leaf_cfs 
                       if not cf.is_empty() and cf.n >= self.min_baseline_cf_points]
        
        if len(baseline_cfs) == 0:
            return {
                'is_outlier': False,
                'distance_to_nearest_cf': None,
                'z_score': None,
            }
        
        # 计算统计量
        all_values = []
        for cf in baseline_cfs:
            centroid = cf.centroid[0]
            n = cf.n
            ss = cf.ss[0]
            ls = cf.ls[0]
            var = max(ss / n - (ls / n) ** 2, 0.01)
            std = np.sqrt(var)
            mean = ls / n
            all_values.append({
                'mean': mean,
                'std': std,
                'n': n,
                'centroid': centroid
            })
        
        if not all_values:
            return {'is_outlier': False}
        
        # 找到最近的分布
        best_dist = float('inf')
        best_stats = None
        
        for stats in all_values:
            dist = abs(value - stats['centroid'])
            if dist < best_dist:
                best_dist = dist
                best_stats = stats
        
        if best_stats is None:
            return {'is_outlier': False}
        
        # 计算 z-score
        std = max(best_stats['std'], 0.01)
        z_score = abs(value - best_stats['mean']) / std
        
        is_outlier = z_score > self.threshold_k
        
        return {
            'is_outlier': is_outlier,
            'distance_to_nearest_cf': best_dist,
            'z_score': z_score,
        }
    
    def _detect_from_cf_tree(self, value: float) -> Dict:
        """
        使用 CF 树检测
        
        只使用点数足够的 CF（n >= min_baseline_cf_points）作为基线，
        避免单个离群点形成的 CF 被误用为基线。
        """
        point = np.array([value], dtype=np.float64)
        leaf_cfs = self.birch_tree.root.get_all_leaf_cfs()
        
        # 只使用点数足够的 CF 作为基线
        baseline_cfs = [cf for cf in leaf_cfs 
                       if not cf.is_empty() and cf.n >= self.min_baseline_cf_points]
        
        if not baseline_cfs:
            return {'is_outlier': False}
        
        # 找到最近的基线 CF
        min_dist = float('inf')
        nearest_cf = None
        
        for cf in baseline_cfs:
            dist = cf.distance_to_point(point)
            if dist < min_dist:
                min_dist = dist
                nearest_cf = cf
        
        if nearest_cf is None:
            return {'is_outlier': False}
        
        # 计算 z-score
        radius = max(nearest_cf.radius, 0.01)
        z_score = min_dist / radius
        
        # 离群判定
        is_outlier = z_score > self.threshold_k
        
        return {
            'is_outlier': is_outlier,
            'distance_to_nearest_cf': min_dist,
            'z_score': z_score,
        }
    
    def get_detection_summary(self) -> Dict:
        """获取检测摘要"""
        return {
            'total_detections': self.total_detections,
            'total_outliers': self.total_outliers,
            'outlier_rate': self.total_outliers / self.total_detections if self.total_detections > 0 else 0,
            'total_alerts': self.total_alerts,
            'consecutive_outliers': self.consecutive_outliers,
            'alert_history': self.alert_history[-10:],  # 最近10条
            'birch_stats': self.birch_tree.get_stats()
        }
    
    def reset(self) -> None:
        """重置检测器"""
        self.consecutive_outliers = 0
        self.detection_history = []
        self.alert_history = []
        self.total_detections = 0
        self.total_outliers = 0
        self.total_alerts = 0
        self.birch_tree.reset()
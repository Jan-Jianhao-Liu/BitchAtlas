"""
BIRCH 树实现

基于 CF (Clustering Feature) 的层次聚类树，支持：
1. 增量数据插入 (O(log n))
2. 在线流式聚类
3. CF 树序列化/反序列化
4. 云端 CF 树合并
"""

import numpy as np
from typing import List, Optional, Tuple
from .cf import CF, CFNode


class BirchTree:
    """
    BIRCH 聚类树
    
    核心数据结构：
    - CF (Clustering Feature): 三元组 (N, LS, SS)
    - CF 树: 层次化结构，叶子节点存储实际 CF
    
    工作流程：
    1. 每个测量值进入 CF 树
    2. 找到最近的叶子 CF，尝试合并
    3. 如果合并后半径 <= 阈值 T，吸收
    4. 否则，创建新的 CF
    5. 叶子 CF 数量超限时分裂
    6. 定期将叶子 CF 序列化上报云端
    
    时间复杂度：O(log n) per insert
    空间复杂度：O(k)，k 为簇数（固定）
    """
    
    def __init__(self, radius_threshold: float = 1.0, 
                 max_children: int = 5,
                 outlier_threshold_k: float = 3.0,
                 consecutive_outlier_limit: int = 3):
        """
        初始化 BIRCH 树
        
        Args:
            radius_threshold: 半径阈值 T (控制簇的紧密度)
            max_children: 最大子节点数 B (控制树的宽度)
            outlier_threshold_k: 离群判定 k 倍数 (k·σ)
            consecutive_outlier_limit: 连续离群次数触发告警
        """
        self.radius_threshold = radius_threshold
        self.max_children = max_children
        self.outlier_threshold_k = outlier_threshold_k
        self.consecutive_outlier_limit = consecutive_outlier_limit
        
        # 树结构
        self.root = CFNode(radius_threshold, max_children)
        
        # 统计
        self.total_points_processed = 0
        self.consecutive_outliers = 0
        self.outlier_count = 0
        
        # 历史记录（用于检测突变）
        self.recent_values: List[float] = []
        self.history_window = 100
    
    def insert(self, value: float, 
               measure_point_id: str = "",
               data_type: str = "") -> Tuple[bool, Optional[int], bool]:
        """
        插入单个测量值
        
        Args:
            value: 测量值
            measure_point_id: 测点ID
            data_type: 数据类型 (底横筋/底纵筋等)
            
        Returns:
            (是否成功插入, 离群索引, 是否触发告警)
        """
        point = np.array([value], dtype=np.float64)
        
        # 检查是否为离群点
        is_outlier = self._check_outlier(point)
        
        if is_outlier:
            self.outlier_count += 1
            self.consecutive_outliers += 1
            
            # 触发告警检查
            should_alert = self.consecutive_outliers >= self.consecutive_outlier_limit
            
            # 仍然插入 CF 树（标记为离群）
            success, _ = self.root.insert(point)
            
            # 添加到历史
            self._update_history(value)
            
            self.total_points_processed += 1
            return success, len(self.root.get_all_leaf_cfs()) - 1, should_alert
        else:
            # 重置连续离群计数
            self.consecutive_outliers = 0
            
            # 正常插入
            success, _ = self.root.insert(point)
            
            # 添加到历史
            self._update_history(value)
            
            self.total_points_processed += 1
            return success, None, False
    
    def insert_batch(self, values: List[float],
                     measure_point_id: str = "",
                     data_type: str = "") -> List[dict]:
        """
        批量插入测量值
        
        Args:
            values: 测量值数组
            measure_point_id: 测点ID
            data_type: 数据类型
            
        Returns:
            每个值的处理结果列表
        """
        results = []
        
        for i, value in enumerate(values):
            success, outlier_idx, alert = self.insert(
                value, measure_point_id, data_type
            )
            
            results.append({
                'index': i,
                'value': value,
                'success': success,
                'is_outlier': outlier_idx is not None,
                'outlier_cf_index': outlier_idx,
                'alert_triggered': alert
            })
        
        return results
    
    def _check_outlier(self, point: np.ndarray) -> bool:
        """
        检查是否为离群点
        
        判定逻辑：
        1. 与最近 CF 的质心距离 > k·σ (CF 半径) → 标记为离群候选
        2. 如果 CF 树为空，使用历史统计
        
        Args:
            point: 数据点
            
        Returns:
            是否为离群点
        """
        leaf_cfs = self.root.get_all_leaf_cfs()
        
        if not leaf_cfs:
            # CF 树为空，使用历史数据判断
            if len(self.recent_values) >= 10:
                mean = np.mean(self.recent_values)
                std = np.std(self.recent_values)
                if std > 0:
                    z_score = abs(point[0] - mean) / std
                    return z_score > self.outlier_threshold_k
            return False
        
        # 与最近 CF 的距离
        min_dist = float('inf')
        for cf in leaf_cfs:
            if not cf.is_empty():
                dist = cf.distance_to_point(point)
                if dist < min_dist:
                    min_dist = dist
                    nearest_radius = cf.radius
        
        # 离群判定：距离 > outlier_threshold_k * radius
        return min_dist > self.outlier_threshold_k * max(nearest_radius, 0.01)
    
    def _update_history(self, value: float) -> None:
        """更新历史记录"""
        self.recent_values.append(value)
        if len(self.recent_values) > self.history_window:
            self.recent_values.pop(0)
    
    def get_clusters(self) -> List[dict]:
        """
        获取当前所有聚类
        
        Returns:
            聚类信息列表
        """
        leaf_cfs = self.root.get_all_leaf_cfs()
        clusters = []
        
        for i, cf in enumerate(leaf_cfs):
            if not cf.is_empty():
                clusters.append({
                    'cluster_id': i,
                    'centroid': cf.centroid.tolist(),
                    'radius': cf.radius,
                    'diameter': cf.diameter,
                    'point_count': cf.n,
                    'cf_data': cf.to_dict()
                })
        
        return clusters
    
    def get_centroids(self) -> List[List[float]]:
        """获取所有簇心"""
        return [cf.centroid.tolist() for cf in self.root.get_all_leaf_cfs() if not cf.is_empty()]
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        base_stats = self.root.get_stats()
        return {
            **base_stats,
            'total_points_processed': self.total_points_processed,
            'outlier_count': self.outlier_count,
            'outlier_rate': self.outlier_count / self.total_points_processed if self.total_points_processed > 0 else 0,
            'consecutive_outliers': self.consecutive_outliers,
            'radius_threshold': self.radius_threshold,
            'max_children': self.max_children,
            'history_size': len(self.recent_values)
        }
    
    def serialize(self) -> dict:
        """
        序列化为字典（用于云端合并）
        
        Returns:
            序列化的树结构
        """
        return {
            'radius_threshold': self.radius_threshold,
            'max_children': self.max_children,
            'total_points': self.total_points_processed,
            'leaf_cfs': [cf.to_dict() for cf in self.root.get_all_leaf_cfs() if not cf.is_empty()],
            'outlier_stats': {
                'total': self.outlier_count,
                'rate': self.outlier_count / self.total_points_processed if self.total_points_processed > 0 else 0
            }
        }
    
    @classmethod
    def deserialize(cls, data: dict) -> 'BirchTree':
        """
        从字典反序列化
        
        Args:
            data: 序列化数据
            
        Returns:
            重建的树
        """
        tree = cls(
            radius_threshold=data['radius_threshold'],
            max_children=data['max_children']
        )
        
        tree.total_points_processed = data.get('total_points', 0)
        
        # 重建 CF 树
        for cf_data in data.get('leaf_cfs', []):
            cf = CF.from_dict(cf_data)
            if not cf.is_empty():
                # 用质心重建
                tree.root.insert(cf.centroid)
        
        tree.outlier_count = data.get('outlier_stats', {}).get('total', 0)
        
        return tree
    
    def merge(self, other: 'BirchTree') -> 'BirchTree':
        """
        合并另一棵 BIRCH 树
        
        用于将多个边缘节点的 CF 树合并为全局模型
        
        Args:
            other: 另一棵树
            
        Returns:
            合并后的新树
        """
        # 获取两棵树的所有 CF
        my_cfs = self.root.get_all_leaf_cfs()
        other_cfs = other.root.get_all_leaf_cfs()
        
        # 创建新树
        new_tree = BirchTree(
            radius_threshold=max(self.radius_threshold, other.radius_threshold),
            max_children=max(self.max_children, other.max_children)
        )
        
        # 插入所有质心
        for cf in my_cfs + other_cfs:
            if not cf.is_empty():
                new_tree.insert(cf.centroid[0])
        
        # 合并统计
        new_tree.total_points_processed = (self.total_points_processed + 
                                           other.total_points_processed)
        new_tree.outlier_count = self.outlier_count + other.outlier_count
        
        return new_tree
    
    def copy(self) -> 'BirchTree':
        """深拷贝"""
        data = self.serialize()
        return BirchTree.deserialize(data)
    
    def reset(self) -> None:
        """重置树"""
        self.root = CFNode(self.radius_threshold, self.max_children)
        self.total_points_processed = 0
        self.consecutive_outliers = 0
        self.outlier_count = 0
        self.recent_values = []
    
    def __len__(self) -> int:
        """当前簇数"""
        return len(self.root.get_all_leaf_cfs())
    
    def __repr__(self) -> str:
        stats = self.get_stats()
        return (f"BirchTree(clusters={stats['num_clusters']}, "
                f"points={stats['total_points_processed']}, "
                f"outliers={stats['outlier_count']})")
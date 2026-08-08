"""
CF (Clustering Feature) 数据结构

CF = (N, LS, SS)
- N: 簇中点数
- LS: 线性求和 (各维度)
- SS: 平方和 (各维度)

支持增量更新和距离计算。
"""

import numpy as np
from typing import List, Optional, Tuple


class CF:
    """
    Clustering Feature 聚类特征向量
    
    CF = (N, LS, SS) 三元组：
    - N: 该簇包含的数据点数
    - LS: 各维度的线性求和 (sum of points)
    - SS: 各维度的平方和 (sum of squares)
    
    支持：
    - 增量添加数据点 (O(d) 时间)
    - 与另一个 CF 合并
    - 计算质心 (centroid)
    - 计算半径 (radius)
    - 计算直径 (diameter)
    - 与点或另一个 CF 的距离
    """
    
    def __init__(self, n: int = 0, ls: Optional[np.ndarray] = None, 
                 ss: Optional[np.ndarray] = None):
        """
        初始化 CF
        
        Args:
            n: 数据点数量
            ls: 线性求和向量 [d]
            ss: 平方和向量 [d]
        """
        self.n = n
        self.ls = ls.astype(np.float64) if ls is not None else None
        self.ss = ss.astype(np.float64) if ss is not None else None
    
    @classmethod
    def from_point(cls, point: np.ndarray) -> 'CF':
        """
        从单个数据点创建 CF
        
        Args:
            point: 数据点 [d]
            
        Returns:
            包含该点的 CF
        """
        point = np.asarray(point, dtype=np.float64)
        return cls(
            n=1,
            ls=point.copy(),
            ss=point * point
        )
    
    def add_point(self, point: np.ndarray) -> None:
        """
        增量添加数据点
        
        O(d) 时间复杂度，d 为维度数
        
        Args:
            point: 数据点 [d]
        """
        point = np.asarray(point, dtype=np.float64)
        if self.ls is None:
            self.ls = point.copy()
            self.ss = point * point
            self.n = 1
        else:
            self.n += 1
            self.ls += point
            self.ss += point * point
    
    def merge(self, other: 'CF') -> 'CF':
        """
        合并两个 CF
        
        返回新的 CF，不修改原对象
        
        Args:
            other: 另一个 CF
            
        Returns:
            合并后的 CF
        """
        if self.ls is None:
            return CF(other.n, other.ls.copy() if other.ls is not None else None,
                     other.ss.copy() if other.ss is not None else None)
        if other.ls is None:
            return CF(self.n, self.ls.copy(), self.ss.copy())
        
        return CF(
            n=self.n + other.n,
            ls=self.ls + other.ls,
            ss=self.ss + other.ss
        )
    
    def merge_inplace(self, other: 'CF') -> None:
        """
        原地合并另一个 CF
        
        Args:
            other: 另一个 CF
        """
        if self.ls is None:
            self.ls = other.ls.copy()
            self.ss = other.ss.copy()
            self.n = other.n
        elif other.ls is not None:
            self.n += other.n
            self.ls += other.ls
            self.ss += other.ss
    
    @property
    def centroid(self) -> np.ndarray:
        """
        计算质心 (LS / N)
        
        Returns:
            质心向量 [d]
        """
        if self.n == 0 or self.ls is None:
            raise ValueError("CF is empty, cannot compute centroid")
        return self.ls / self.n
    
    @property
    def radius(self) -> float:
        """
        计算半径 (R)
        
        R = sqrt(SS/N - (LS/N)^2)
        
        Returns:
            半径值
        """
        if self.n == 0 or self.ss is None or self.ls is None:
            return 0.0
        centroid = self.centroid
        variance = self.ss / self.n - centroid * centroid
        variance = np.maximum(variance, 0)  # 数值稳定性
        return float(np.sqrt(np.sum(variance)))
    
    @property
    def diameter(self) -> float:
        """
        计算直径 (D)
        
        D = sqrt(2 * (N * SS - LS^2)) / N
        
        Returns:
            直径值
        """
        if self.n == 0 or self.ss is None or self.ls is None:
            return 0.0
        # D^2 = (2 * sum(SS - LS^2/N)) / N
        d_squared = 2.0 * (np.sum(self.ss) - np.sum(self.ls * self.ls) / self.n) / self.n
        return float(np.sqrt(max(0, d_squared)))
    
    def distance_to_point(self, point: np.ndarray) -> float:
        """
        计算到点的欧氏距离
        
        Args:
            point: 数据点 [d]
            
        Returns:
            距离值
        """
        point = np.asarray(point, dtype=np.float64)
        return float(np.sqrt(np.sum((self.centroid - point) ** 2)))
    
    def distance_to_cf(self, other: 'CF') -> float:
        """
        计算与另一个 CF 的欧氏距离
        
        Args:
            other: 另一个 CF
            
        Returns:
            距离值
        """
        return float(np.sqrt(np.sum((self.centroid - other.centroid) ** 2)))
    
    def merge_distance(self, other: 'CF') -> float:
        """
        合并距离：合并后的 CF 直径
        
        Args:
            other: 另一个 CF
            
        Returns:
            合并后的直径
        """
        merged = self.merge(other)
        return merged.diameter
    
    def is_empty(self) -> bool:
        """检查是否为空"""
        return self.n == 0
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'n': self.n,
            'ls': self.ls.tolist() if self.ls is not None else [],
            'ss': self.ss.tolist() if self.ss is not None else []
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'CF':
        """从字典创建"""
        return cls(
            n=data['n'],
            ls=np.array(data['ls']) if data['ls'] else None,
            ss=np.array(data['ss']) if data['ss'] else None
        )
    
    def __repr__(self) -> str:
        if self.n == 0:
            return f"CF(empty)"
        dim = len(self.ls) if self.ls is not None else 0
        return f"CF(n={self.n}, dim={dim}, radius={self.radius:.4f})"
    
    def __len__(self) -> int:
        return self.n
    
    def __eq__(self, other: 'CF') -> bool:
        if not isinstance(other, CF):
            return False
        return (self.n == other.n and 
                np.allclose(self.ls, other.ls) if self.ls is not None and other.ls is not None else self.ls is None == other.ls is None and
                np.allclose(self.ss, other.ss) if self.ss is not None and other.ss is not None else self.ss is None == other.ss is None)


class CFNode:
    """
    CF 树节点
    
    可以是内部节点（包含子节点引用）或叶子节点（包含 CF 列表）
    
    属性：
        - cf: 该节点的聚合 CF
        - children: 子节点列表（内部节点）
        - leaf_cfs: 叶子 CF 列表（叶子节点）
        - is_leaf: 是否为叶子节点
        - radius_threshold: 半径阈值 T
    """
    
    def __init__(self, radius_threshold: float = 1.0, max_children: int = 5):
        """
        初始化 CF 节点
        
        Args:
            radius_threshold: 半径阈值 T
            max_children: 最大子节点数 B
        """
        self.cf = CF()
        self.children: List['CFNode'] = []
        self.leaf_cfs: List[CF] = []
        self.is_leaf = True
        self.radius_threshold = radius_threshold
        self.max_children = max_children
    
    def insert(self, point: np.ndarray) -> Tuple[bool, Optional[int]]:
        """
        插入数据点
        
        Args:
            point: 数据点 [d]
            
        Returns:
            (是否插入成功, 离群索引如果为离群点)
        """
        point = np.asarray(point, dtype=np.float64)
        
        if self.is_leaf:
            return self._insert_leaf(point)
        else:
            # 内部节点：找最近的子节点
            best_child = None
            best_dist = float('inf')
            
            for i, child in enumerate(self.children):
                dist = child.cf.distance_to_point(point)
                if dist < best_dist:
                    best_dist = dist
                    best_child = child
                    best_idx = i
            
            if best_child is None:
                return False, None
            
            success, outlier_idx = best_child.insert(point)
            
            # 更新当前节点的 CF
            self._update_cf_from_children()
            
            # 如果子节点需要分裂
            if best_child.cf.radius > self.radius_threshold and len(best_child.children) > 0:
                self._split_child(best_idx)
            
            return success, outlier_idx
    
    def _insert_leaf(self, point: np.ndarray) -> Tuple[bool, Optional[int]]:
        """
        在叶子节点插入数据点
        
        策略：
        1. 找最近的 CF
        2. 检查合并后半径是否 <= 阈值
        3. 如果满足条件，合并
        4. 如果不满足，创建新的 CF
        5. 如果 CF 数量超限，分裂
        
        Args:
            point: 数据点
            
        Returns:
            (是否插入成功, 离群索引)
        """
        if len(self.leaf_cfs) == 0:
            # 空叶子节点，创建新 CF
            self.leaf_cfs.append(CF.from_point(point))
            self._update_cf_from_children()
            return True, None
        
        # 找最近的 CF
        best_idx = 0
        best_dist = float('inf')
        
        for i, cf in enumerate(self.leaf_cfs):
            dist = cf.distance_to_point(point)
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        
        # 检查合并后是否在阈值内
        target_cf = self.leaf_cfs[best_idx]
        merged = target_cf.merge(CF.from_point(point))
        
        if merged.radius <= self.radius_threshold:
            # 合并
            self.leaf_cfs[best_idx] = merged
            self._update_cf_from_children()
            return True, None
        else:
            # 创建新的 CF
            new_cf = CF.from_point(point)
            
            if len(self.leaf_cfs) < self.max_children:
                self.leaf_cfs.append(new_cf)
                self._update_cf_from_children()
                return True, None
            else:
                # 需要分裂
                self.leaf_cfs.append(new_cf)
                self._split_leaf()
                return True, None
    
    def _split_leaf(self) -> None:
        """
        分裂叶子节点
        
        使用最远点策略：
        1. 选择两个距离最远的 CF 作为种子
        2. 将其他 CF 分配给最近的种子
        3. 创建两个新的叶子节点
        """
        # 找两个最远的 CF
        cf_list = self.leaf_cfs
        if len(cf_list) < 2:
            return
        
        # 找到距离最远的两个 CF
        max_dist = -1
        seed_i, seed_j = 0, 1
        
        for i in range(len(cf_list)):
            for j in range(i + 1, len(cf_list)):
                dist = cf_list[i].distance_to_cf(cf_list[j])
                if dist > max_dist:
                    max_dist = dist
                    seed_i, seed_j = i, j
        
        # 按距离分配
        new_leaf_1 = CFNode(self.radius_threshold, self.max_children)
        new_leaf_2 = CFNode(self.radius_threshold, self.max_children)
        
        for i, cf in enumerate(cf_list):
            if i == seed_i:
                new_leaf_1.leaf_cfs.append(cf)
            elif i == seed_j:
                new_leaf_2.leaf_cfs.append(cf)
            else:
                dist_to_1 = cf.distance_to_cf(cf_list[seed_i])
                dist_to_2 = cf.distance_to_cf(cf_list[seed_j])
                if dist_to_1 <= dist_to_2:
                    new_leaf_1.leaf_cfs.append(cf)
                else:
                    new_leaf_2.leaf_cfs.append(cf)
        
        # 更新结构
        new_leaf_1._update_cf_from_children()
        new_leaf_2._update_cf_from_children()
        
        self.is_leaf = False
        self.leaf_cfs = []
        self.children = [new_leaf_1, new_leaf_2]
        self._update_cf_from_children()
    
    def _split_child(self, child_idx: int) -> None:
        """
        分裂子节点
        
        Args:
            child_idx: 子节点索引
        """
        child = self.children[child_idx]
        
        if child.is_leaf:
            child._split_leaf()
        else:
            # 内部节点分裂：将子节点分到两个新节点
            # 简化处理：直接使用 child 的 children 构建
            pass
    
    def _update_cf_from_children(self) -> None:
        """从子节点/CF 更新当前节点的 CF"""
        self.cf = CF()
        
        if self.is_leaf:
            for cf in self.leaf_cfs:
                self.cf.merge_inplace(cf)
        else:
            for child in self.children:
                self.cf.merge_inplace(child.cf)
    
    def get_all_leaf_cfs(self) -> List[CF]:
        """获取所有叶子节点的 CF"""
        if self.is_leaf:
            return self.leaf_cfs.copy()
        else:
            result = []
            for child in self.children:
                result.extend(child.get_all_leaf_cfs())
            return result
    
    def get_centroids(self) -> List[np.ndarray]:
        """获取所有簇心"""
        cfs = self.get_all_leaf_cfs()
        return [cf.centroid for cf in cfs if not cf.is_empty()]
    
    def to_list(self) -> List[dict]:
        """转换为列表"""
        cfs = self.get_all_leaf_cfs()
        return [cf.to_dict() for cf in cfs]
    
    def merge_trees(self, other: 'CFNode') -> 'CFNode':
        """
        合并另一棵 CF 树
        
        Args:
            other: 另一棵 CF 树
            
        Returns:
            合并后的新根节点
        """
        # 获取两棵树的所有叶子 CF
        my_cfs = self.get_all_leaf_cfs()
        other_cfs = other.get_all_leaf_cfs()
        
        # 创建新树
        new_node = CFNode(self.radius_threshold, self.max_children)
        
        # 插入所有 CF
        # 简化：直接插入所有点
        for cf in my_cfs + other_cfs:
            if not cf.is_empty():
                # 用质心代表该 CF 插入
                new_node.insert(cf.centroid)
        
        return new_node
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        leaf_cfs = self.get_all_leaf_cfs()
        total_points = sum(cf.n for cf in leaf_cfs)
        return {
            'total_points': total_points,
            'num_clusters': len(leaf_cfs),
            'avg_points_per_cluster': total_points / len(leaf_cfs) if leaf_cfs else 0,
            'max_cluster_size': max((cf.n for cf in leaf_cfs), default=0),
            'min_cluster_size': min((cf.n for cf in leaf_cfs), default=0),
        }
    
    def __repr__(self) -> str:
        leaf_info = f"leaf_cfs={len(self.leaf_cfs)}" if self.is_leaf else f"children={len(self.children)}"
        return f"CFNode(is_leaf={self.is_leaf}, {leaf_info}, cf={self.cf})"
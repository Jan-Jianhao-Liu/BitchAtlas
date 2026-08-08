"""
CF 树序列化器

用于边缘 CF 树与云端的数据传输：
1. JSON 序列化（用于 MQTT 传输）
2. 紧凑二进制格式（用于高效存储）
3. 支持增量更新和合并
"""

import json
import numpy as np
from typing import Dict, List, Optional, Tuple
from .cf import CF, CFNode
from .birch_tree import BirchTree


class CFSerializer:
    """
    CF 树序列化器
    
    支持多种序列化格式：
    1. JSON 格式（易读，适合调试和 MQTT 传输）
    2. 紧凑格式（高效，适合批量传输）
    """
    
    @staticmethod
    def to_json(tree: BirchTree, gateway_code: str = "",
                measure_point_id: str = "", 
                data_type: str = "") -> Dict:
        """
        序列化为 JSON 兼容的字典
        
        Args:
            tree: BIRCH 树
            gateway_code: 网关编号
            measure_point_id: 测点ID
            data_type: 数据类型
            
        Returns:
            JSON 可序列化的字典
        """
        leaf_cfs = tree.root.get_all_leaf_cfs()
        
        # 聚合簇心
        centroids = []
        for cf in leaf_cfs:
            if not cf.is_empty():
                centroids.append({
                    'n': cf.n,
                    'centroid': cf.centroid.tolist(),
                    'radius': cf.radius,
                    'diameter': cf.diameter,
                    'ls': cf.ls.tolist() if cf.ls is not None else [],
                    'ss': cf.ss.tolist() if cf.ss is not None else []
                })
        
        return {
            'version': '1.0',
            'tree_id': f"{gateway_code}_{measure_point_id}_{data_type}",
            'gateway_code': gateway_code,
            'measure_point_id': measure_point_id,
            'data_type': data_type,
            'timestamp': np.datetime64('now', 'ms').tolist(),
            'config': {
                'radius_threshold': tree.radius_threshold,
                'max_children': tree.max_children
            },
            'stats': tree.get_stats(),
            'centroids': centroids,
            'serialization_method': 'birch_cf_v1'
        }
    
    @staticmethod
    def from_json(data: Dict) -> BirchTree:
        """
        从 JSON 字典反序列化
        
        Args:
            data: JSON 数据
            
        Returns:
            重建的 BIRCH 树
        """
        config = data.get('config', {})
        tree = BirchTree(
            radius_threshold=config.get('radius_threshold', 1.0),
            max_children=config.get('max_children', 5)
        )
        
        stats = data.get('stats', {})
        # 使用 total_points_processed (如果存在) 或 total_points
        tree.total_points_processed = stats.get('total_points_processed', 
                                    stats.get('total_points', 0))
        
        # 直接重建 CF 节点
        for centroid_data in data.get('centroids', []):
            n = centroid_data['n']
            centroid = np.array(centroid_data['centroid'])
            ls = np.array(centroid_data.get('ls', centroid * n))
            ss = np.array(centroid_data.get('ss', 
                        (ls * ls / n if n > 0 else ls * ls).tolist()))
            
            # 创建 CF 并直接添加到叶子节点
            cf = CF(n=n, ls=ls, ss=ss)
            tree.root.leaf_cfs.append(cf)
        
        # 更新根节点的聚合 CF
        tree.root._update_cf_from_children()
        
        return tree
    
    @staticmethod
    def to_incremental_update(tree: BirchTree, 
                              previous_centroids: List[Dict],
                              gateway_code: str = "",
                              measure_point_id: str = "",
                              data_type: str = "") -> Dict:
        """
        生成增量更新数据（仅传输变化的部分）
        
        Args:
            tree: 当前 BIRCH 树
            previous_centroids: 上次的簇心列表
            gateway_code: 网关编号
            measure_point_id: 测点ID
            data_type: 数据类型
            
        Returns:
            增量更新数据
        """
        current_centroids = tree.root.get_all_leaf_cfs()
        
        updates = []
        new_cfs = []
        
        # 检查每个当前 CF 是否需要更新
        for cf in current_centroids:
            if cf.is_empty():
                continue
            
            # 简化处理：传输所有非空 CF
            updates.append({
                'n': cf.n,
                'centroid': cf.centroid.tolist(),
                'radius': cf.radius,
                'diameter': cf.diameter
            })
        
        return {
            'version': '1.0',
            'update_type': 'incremental',
            'tree_id': f"{gateway_code}_{measure_point_id}_{data_type}",
            'gateway_code': gateway_code,
            'measure_point_id': measure_point_id,
            'data_type': data_type,
            'timestamp': np.datetime64('now', 'ms').tolist(),
            'new_centroids': len(updates),
            'centroid_updates': updates
        }
    
    @staticmethod
    def merge_from_json_list(json_list: List[Dict]) -> BirchTree:
        """
        从多个 JSON 树数据合并为单一 BIRCH 树
        
        用于云端将多个边缘 CF 树合并
        
        Args:
            json_list: 多个序列化的树数据
            
        Returns:
            合并后的 BIRCH 树
        """
        if not json_list:
            return BirchTree()
        
        # 使用第一个树作为基础
        base_tree = CFSerializer.from_json(json_list[0])
        
        # 依次合并其他树
        for data in json_list[1:]:
            other_tree = CFSerializer.from_json(data)
            base_tree = base_tree.merge(other_tree)
        
        return base_tree
    
    @staticmethod
    def validate_format(data: Dict) -> Tuple[bool, str]:
        """
        验证序列化数据格式
        
        Args:
            data: 待验证数据
            
        Returns:
            (是否有效, 错误信息)
        """
        required_fields = ['version', 'centroids', 'stats']
        
        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"
        
        if 'centroids' in data:
            for i, centroid in enumerate(data['centroids']):
                if 'centroid' not in centroid:
                    return False, f"Centroid {i} missing 'centroid' field"
                if 'n' not in centroid:
                    return False, f"Centroid {i} missing 'n' field"
        
        return True, ""
    
    @staticmethod
    def estimate_size(tree_data: Dict) -> int:
        """
        估算序列化数据大小（字节）
        
        Args:
            tree_data: 序列化的树数据
            
        Returns:
            估算大小
        """
        json_str = json.dumps(tree_data)
        return len(json_str.encode('utf-8'))
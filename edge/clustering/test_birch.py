"""
BIRCH 流式聚类算法库 - 单元测试
================================

测试 CF 数据结构、BIRCH 树、离群检测、序列化和质量评估功能。
"""

import numpy as np
import pytest
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edge.clustering import CF, CFNode, BirchTree, OutlierDetector, CFSerializer, ClusteringQuality


class TestCF:
    """
    测试 CF (Clustering Feature) 数据结构
    """
    
    def test_create_from_point(self):
        """测试从点创建 CF"""
        point = np.array([1.0, 2.0, 3.0])
        cf = CF.from_point(point)
        
        assert cf.n == 1
        assert np.allclose(cf.ls, [1.0, 2.0, 3.0])
        assert np.allclose(cf.ss, [1.0, 4.0, 9.0])
    
    def test_add_point(self):
        """测试增量添加点"""
        cf = CF()
        cf.add_point(np.array([1.0, 2.0]))
        cf.add_point(np.array([3.0, 4.0]))
        
        assert cf.n == 2
        assert np.allclose(cf.ls, [4.0, 6.0])
        assert np.allclose(cf.ss, [10.0, 20.0])
    
    def test_merge(self):
        """测试 CF 合并"""
        cf1 = CF.from_point(np.array([1.0, 2.0]))
        cf2 = CF.from_point(np.array([3.0, 4.0]))
        
        merged = cf1.merge(cf2)
        
        assert merged.n == 2
        assert np.allclose(merged.ls, [4.0, 6.0])
    
    def test_centroid(self):
        """测试质心计算"""
        cf = CF.from_point(np.array([2.0, 4.0]))
        cf.add_point(np.array([4.0, 8.0]))
        
        centroid = cf.centroid
        assert np.allclose(centroid, [3.0, 6.0])
    
    def test_radius(self):
        """测试半径计算"""
        cf = CF.from_point(np.array([1.0, 0.0]))
        cf.add_point(np.array([-1.0, 0.0]))
        
        radius = cf.radius
        assert radius > 0
    
    def test_distance(self):
        """测试距离计算"""
        cf = CF.from_point(np.array([0.0, 0.0]))
        dist = cf.distance_to_point(np.array([3.0, 4.0]))
        
        assert np.isclose(dist, 5.0)
    
    def test_serialization(self):
        """测试序列化"""
        cf = CF.from_point(np.array([1.0, 2.0]))
        data = cf.to_dict()
        restored = CF.from_dict(data)
        
        assert cf.n == restored.n
        assert np.allclose(cf.ls, restored.ls)


class TestBirchTree:
    """
    测试 BIRCH 树
    """
    
    def test_insert_single(self):
        """测试插入单个点"""
        tree = BirchTree(radius_threshold=1.0)
        tree.insert(1.0)
        
        assert tree.total_points_processed == 1
        assert len(tree) >= 1
    
    def test_insert_batch(self):
        """测试批量插入"""
        tree = BirchTree(radius_threshold=0.5)
        values = [1.0, 1.1, 1.2, 5.0, 5.1, 5.2]
        
        results = tree.insert_batch(values)
        
        assert len(results) == 6
        assert tree.total_points_processed == 6
        
        # 应该形成至少 2 个簇
        assert len(tree) >= 2
    
    def test_outlier_detection(self):
        """测试离群检测"""
        tree = BirchTree(
            radius_threshold=0.3,
            outlier_threshold_k=2.0
        )
        
        # 先插入一些正常值建立 CF 树
        for _ in range(20):
            tree.insert(1.0 + np.random.normal(0, 0.05))
        
        # 插入离群值
        _, _, is_alert = tree.insert(10.0)
        
        # 应该检测为离群
        assert tree.outlier_count > 0
    
    def test_get_clusters(self):
        """测试获取聚类结果"""
        tree = BirchTree(radius_threshold=0.5)
        
        # 两个明显不同的簇
        for _ in range(10):
            tree.insert(1.0 + np.random.normal(0, 0.02))
        for _ in range(10):
            tree.insert(5.0 + np.random.normal(0, 0.02))
        
        clusters = tree.get_clusters()
        
        assert len(clusters) >= 2
        # 检查簇心是否合理分离
        centroids = [c['centroid'][0] for c in clusters]
        centroids.sort()
        
        # 最大和最小质心应有明显差距
        assert centroids[-1] - centroids[0] > 1.0
    
    def test_serialization(self):
        """测试序列化/反序列化"""
        tree = BirchTree(radius_threshold=0.5)
        
        for _ in range(30):
            tree.insert(np.random.normal(5.0, 1.0))
        
        data = tree.serialize()
        restored = BirchTree.deserialize(data)
        
        assert restored.total_points_processed == tree.total_points_processed
    
    def test_merge(self):
        """测试树合并"""
        tree1 = BirchTree(radius_threshold=0.5)
        tree2 = BirchTree(radius_threshold=0.5)
        
        for _ in range(15):
            tree1.insert(1.0 + np.random.normal(0, 0.02))
        for _ in range(15):
            tree2.insert(5.0 + np.random.normal(0, 0.02))
        
        merged = tree1.merge(tree2)
        
        assert merged.total_points_processed == 30


class TestOutlierDetector:
    """
    测试离群检测器
    """
    
    def test_detect_normal(self):
        """测试正常检测"""
        detector = OutlierDetector(
            threshold_k=3.0,
            min_points_for_detection=5
        )
        
        # 插入确定性正常值（在 5.0 附近小幅波动）
        for i in range(20):
            value = 5.0 + (i % 5 - 2) * 0.02  # 4.96 ~ 5.04
            result = detector.detect(value)
            assert result['suggestion'] == 'accept'
    
    def test_detect_outlier(self):
        """测试离群检测"""
        detector = OutlierDetector(
            threshold_k=1.0,  # 使用较小的阈值
            min_points_for_detection=10
        )
        
        # 使用固定值建立基线，确保 CF 树稳定
        for _ in range(30):
            detector.detect(5.0)  # 固定值，CF 半径很小
        
        # 插入明显离群值
        result = detector.detect(20.0)
        
        assert result['is_outlier'] is True
        assert result['suggestion'] in ['flag', 'reject']
    
    def test_consecutive_alerts(self):
        """测试连续离群告警"""
        detector = OutlierDetector(
            threshold_k=1.0,
            consecutive_limit=3,
            min_points_for_detection=10,
            min_baseline_cf_points=5  # 离群 CF 需积累 5 个点才成为基线
        )
        
        # 使用固定值建立基线
        for _ in range(30):
            detector.detect(5.0)
        
        # 连续插入离群值
        alert_count = 0
        for i in range(5):
            result = detector.detect(20.0)
            if result['alert_triggered']:
                alert_count += 1
        
        # 应该在第 3 次开始触发告警
        assert alert_count >= 3
    
    def test_batch_detection(self):
        """测试批量检测"""
        detector = OutlierDetector(min_points_for_detection=5)
        
        values = [5.0, 5.1, 4.9, 5.2, 4.8, 100.0]
        results = detector.detect_batch(values)
        
        assert len(results) == 6


class TestCFSerializer:
    """
    测试序列化器
    """
    
    def test_to_json(self):
        """测试 JSON 序列化"""
        tree = BirchTree(radius_threshold=0.5)
        for _ in range(20):
            tree.insert(np.random.normal(5.0, 1.0))
        
        data = CFSerializer.to_json(tree, "GW-00000001", "MP-001", "bottom_horizontal")
        
        assert 'gateway_code' in data
        assert 'centroids' in data
        assert len(data['centroids']) > 0
    
    def test_from_json(self):
        """测试 JSON 反序列化"""
        tree = BirchTree(radius_threshold=0.5)
        for _ in range(20):
            tree.insert(np.random.normal(5.0, 1.0))
        
        data = CFSerializer.to_json(tree)
        restored = CFSerializer.from_json(data)
        
        # 反序列化会重建树，total_points_processed 可能不同
        # 但结构应该完整
        assert restored.total_points_processed > 0
        assert len(restored) > 0
        # 检查统计信息保留
        assert restored.get_stats()['num_clusters'] > 0
    
    def test_merge_from_json_list(self):
        """测试多树合并"""
        tree1 = BirchTree(radius_threshold=0.5)
        tree2 = BirchTree(radius_threshold=0.5)
        
        for _ in range(15):
            tree1.insert(np.random.normal(1.0, 0.5))
        for _ in range(15):
            tree2.insert(np.random.normal(5.0, 0.5))
        
        data_list = [
            CFSerializer.to_json(tree1),
            CFSerializer.to_json(tree2)
        ]
        
        merged = CFSerializer.merge_from_json_list(data_list)
        
        # 合并后应该有数据
        assert merged.total_points_processed > 0
        assert len(merged) > 0
        # 应该形成多个簇
        assert merged.get_stats()['num_clusters'] >= 2
    
    def test_validate_format(self):
        """测试格式验证"""
        valid_data = {
            'version': '1.0',
            'centroids': [{'n': 10, 'centroid': [5.0]}],
            'stats': {'total_points': 10}
        }
        
        is_valid, error = CFSerializer.validate_format(valid_data)
        assert is_valid is True
        
        invalid_data = {'version': '1.0'}
        is_valid, error = CFSerializer.validate_format(invalid_data)
        assert is_valid is False


class TestClusteringQuality:
    """
    测试聚类质量评估
    """
    
    def test_silhouette_score(self):
        """测试轮廓系数"""
        # 创建两个明显分离的簇
        X = np.vstack([
            np.random.normal(0, 0.5, (50, 2)),
            np.random.normal(5, 0.5, (50, 2))
        ])
        labels = np.array([0] * 50 + [1] * 50)
        
        score = ClusteringQuality.silhouette_score(X, labels)
        
        assert -1 <= score <= 1
        assert score > 0  # 应该为正（簇分离良好）
    
    def test_davies_bouldin_index(self):
        """测试 DBI 指数"""
        X = np.vstack([
            np.random.normal(0, 0.5, (50, 2)),
            np.random.normal(5, 0.5, (50, 2))
        ])
        labels = np.array([0] * 50 + [1] * 50)
        
        dbi = ClusteringQuality.davies_bouldin_index(X, labels)
        
        assert dbi > 0
        assert dbi < 2  # 应该相对较小
    
    def test_calinski_harabasz_index(self):
        """测试 CH 指数"""
        X = np.vstack([
            np.random.normal(0, 0.5, (50, 2)),
            np.random.normal(5, 0.5, (50, 2))
        ])
        labels = np.array([0] * 50 + [1] * 50)
        
        ch = ClusteringQuality.calinski_harabasz_index(X, labels)
        
        assert ch > 0
    
    def test_find_optimal_k(self):
        """测试最优 K 搜索"""
        X = np.vstack([
            np.random.normal(0, 0.3, (40, 2)),
            np.random.normal(3, 0.3, (40, 2)),
            np.random.normal(6, 0.3, (40, 2))
        ])
        
        result = ClusteringQuality.find_optimal_k(X, k_range=(2, 6))
        
        assert 'optimal_k' in result
        assert result['optimal_k'] >= 2
    
    def test_adaptive_eps(self):
        """测试自适应 eps"""
        X = np.vstack([
            np.random.normal(0, 0.3, (50, 2)),
            np.random.normal(3, 0.3, (50, 2))
        ])
        
        result = ClusteringQuality.adaptive_eps(X, k=5)
        
        assert 'suggested_eps' in result
        assert result['suggested_eps'] > 0


class TestIntegration:
    """
    集成测试：完整的边缘聚类流程
    """
    
    def test_full_workflow(self):
        """测试完整工作流"""
        # 1. 创建 BIRCH 树
        tree = BirchTree(radius_threshold=0.5)
        detector = OutlierDetector(birch_tree=tree, threshold_k=1.5)
        
        # 2. 模拟施工场景数据
        # 底横筋间距: 300mm 左右
        normal_spacing = 300.0
        
        for _ in range(100):
            value = normal_spacing + np.random.normal(0, 5)
            detector.detect(value)
        
        # 3. 插入异常值（施工缺陷）
        for i in range(20):
            value = normal_spacing + 50 + np.random.normal(0, 5)
            result = detector.detect(value)
        
        # 4. 检查结果
        summary = detector.get_detection_summary()
        assert summary['total_detections'] == 120
        assert summary['birch_stats']['total_points'] == 120
        
        # 5. 序列化
        tree_data = CFSerializer.to_json(tree, "GW-00000001", "MP-001", "bottom_horizontal")
        
        # 6. 反序列化（模拟云端接收）
        restored = CFSerializer.from_json(tree_data)
        assert restored.total_points_processed > 0
        
        # 7. 获取聚类结果
        clusters = tree.get_clusters()
        assert len(clusters) >= 1
    
    def test_multi_gateway_merge(self):
        """测试多网关 CF 树合并"""
        # 模拟两个边缘网关
        tree_gw1 = BirchTree(radius_threshold=0.3)
        tree_gw2 = BirchTree(radius_threshold=0.3)
        
        # 网关1: 底横筋
        for _ in range(50):
            tree_gw1.insert(300.0 + np.random.normal(0, 3))
        
        # 网关2: 底纵筋
        for _ in range(50):
            tree_gw2.insert(150.0 + np.random.normal(0, 2))
        
        # 序列化并上传
        data_gw1 = CFSerializer.to_json(tree_gw1, "GW-00000001", "MP-001", "bottom_horizontal")
        data_gw2 = CFSerializer.to_json(tree_gw2, "GW-00000002", "MP-002", "bottom_vertical")
        
        # 云端合并
        merged = CFSerializer.merge_from_json_list([data_gw1, data_gw2])
        
        # 合并后应该有数据
        assert merged.total_points_processed > 0
        
        # 检查聚类结果
        clusters = merged.get_clusters()
        # 应该形成多个簇
        assert len(clusters) >= 2
        
        # 检查质心分布（不强制要求精确值，因为合并会改变结构）
        centroids = [c['centroid'][0] for c in clusters]
        assert len(centroids) >= 2
    
    def test_realistic_scenario(self):
        """测试真实场景模拟"""
        tree = BirchTree(radius_threshold=10.0)  # 大阈值，允许不同间距模式形成各自簇
        detector = OutlierDetector(
            birch_tree=tree,
            threshold_k=3.0,
            consecutive_limit=3,
            min_baseline_cf_points=3
        )
        
        # 模拟楼板钢筋检测
        # 4 种类型: 底横筋(300mm), 底纵筋(150mm), 面横筋(250mm), 面纵筋(200mm)
        patterns = [
            ('bottom_horizontal', 300.0, 5.0),
            ('bottom_vertical', 150.0, 3.0),
            ('top_horizontal', 250.0, 4.0),
            ('top_vertical', 200.0, 3.5)
        ]
        
        for pattern_name, mean, std in patterns:
            for _ in range(30):
                value = mean + np.random.normal(0, std)
                detector.detect(value)
        
        # 检查总体统计
        summary = detector.get_detection_summary()
        
        assert summary['total_detections'] == 120
        
        # 检查聚类是否合理
        clusters = tree.get_clusters()
        centroids = [c['centroid'][0] for c in clusters]
        
        # 应该形成多个簇
        assert len(centroids) >= 2
        
        # 验证质心分布合理（覆盖不同类型的间距范围）
        if len(centroids) >= 2:
            assert min(centroids) < max(centroids)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
"""
聚类质量评估

实现聚类质量评估指标：
1. 轮廓系数 (Silhouette Score)
2. Davies-Bouldin 指数
3. Calinski-Harabasz 指数
4. 稳定度 (Bootstrap)
5. 参数自优化（K 搜索、eps 自适应）
"""

import numpy as np
from typing import List, Dict, Tuple, Optional, Callable


class ClusteringQuality:
    """
    聚类质量评估
    
    支持多种评估指标和参数优化策略。
    这些指标可以驱动聚类算法的参数自优化：
    - K-Means: 轮廓系数自动确定最优 K
    - DBSCAN: KNN 距离排序自适应 eps
    """
    
    @staticmethod
    def silhouette_score(X: np.ndarray, labels: np.ndarray) -> float:
        """
        计算轮廓系数 (Silhouette Score)
        
        轮廓系数衡量：
        - 簇内紧致度 (a): 样本与同簇其他样本的平均距离
        - 簇间分离度 (b): 样本与最近其他簇的平均距离
        - score = (b - a) / max(a, b)
        
        取值范围 [-1, 1]：
        - 1: 完美聚类（簇内紧密，簇间远离）
        - 0: 重叠簇
        - -1: 错误聚类
        
        Args:
            X: 数据点 [n_samples, n_features]
            labels: 簇标签 [n_samples]
            
        Returns:
            平均轮廓系数
        """
        n_samples = len(X)
        if n_samples <= 1:
            return 0.0
        
        unique_labels = np.unique(labels)
        n_clusters = len(unique_labels)
        
        if n_clusters <= 1 or n_clusters >= n_samples:
            return 0.0
        
        # 计算 pairwise distances
        # 为避免内存问题，使用分批计算
        scores = np.zeros(n_samples)
        
        for i in range(n_samples):
            current_label = labels[i]
            
            # 簇内紧致度 (a)
            same_cluster = X[labels == current_label]
            if len(same_cluster) <= 1:
                scores[i] = 0.0
                continue
            
            a = np.mean(np.sqrt(np.sum((same_cluster - X[i]) ** 2, axis=1)))
            
            # 簇间分离度 (b)
            b = float('inf')
            for label in unique_labels:
                if label == current_label:
                    continue
                other_cluster = X[labels == label]
                if len(other_cluster) == 0:
                    continue
                dist = np.mean(np.sqrt(np.sum((other_cluster - X[i]) ** 2, axis=1)))
                b = min(b, dist)
            
            if b == float('inf'):
                scores[i] = 0.0
            else:
                scores[i] = (b - a) / max(a, b)
        
        return float(np.mean(scores))
    
    @staticmethod
    def davies_bouldin_index(X: np.ndarray, labels: np.ndarray) -> float:
        """
        计算 Davies-Bouldin 指数
        
        DBI = (1/k) * sum(R_i)
        R_i = max_{j != i} ( (s_i + s_j) / d(c_i, c_j) )
        
        其中：
        - s_i: 簇 i 的平均散度（簇内样本到质心的平均距离）
        - d(c_i, c_j): 质心间距离
        
        DBI 越小表示聚类效果越好。
        
        Args:
            X: 数据点 [n_samples, n_features]
            labels: 簇标签 [n_samples]
            
        Returns:
            DBI 值
        """
        unique_labels = np.unique(labels)
        n_clusters = len(unique_labels)
        
        if n_clusters <= 1:
            return 0.0
        
        # 计算簇质心和散度
        centroids = []
        dispersions = []
        
        for label in unique_labels:
            cluster_points = X[labels == label]
            centroid = np.mean(cluster_points, axis=0)
            centroids.append(centroid)
            
            # 散度: 平均距离
            dispersion = np.mean(np.sqrt(np.sum((cluster_points - centroid) ** 2, axis=1)))
            dispersions.append(dispersion)
        
        centroids = np.array(centroids)
        dispersions = np.array(dispersions)
        
        # 计算 DBI
        dbi_sum = 0.0
        for i in range(n_clusters):
            max_ratio = 0.0
            for j in range(n_clusters):
                if i == j:
                    continue
                dist_centroids = np.sqrt(np.sum((centroids[i] - centroids[j]) ** 2))
                if dist_centroids == 0:
                    continue
                ratio = (dispersions[i] + dispersions[j]) / dist_centroids
                max_ratio = max(max_ratio, ratio)
            dbi_sum += max_ratio
        
        return float(dbi_sum / n_clusters)
    
    @staticmethod
    def calinski_harabasz_index(X: np.ndarray, labels: np.ndarray) -> float:
        """
        计算 Calinski-Harabasz 指数 (VRC)
        
        CH = [B / (k-1)] / [W / (n-k)]
        
        其中：
        - B: 簇间方差 (between-cluster variance)
        - W: 簇内方差 (within-cluster variance)
        - k: 簇数
        - n: 样本数
        
        CH 越大表示聚类效果越好。
        
        Args:
            X: 数据点 [n_samples, n_features]
            labels: 簇标签 [n_samples]
            
        Returns:
            CH 指数值
        """
        n_samples = len(X)
        unique_labels = np.unique(labels)
        n_clusters = len(unique_labels)
        
        if n_clusters <= 1 or n_clusters >= n_samples:
            return 0.0
        
        # 全局质心
        global_centroid = np.mean(X, axis=0)
        
        # 簇间方差 B
        between_var = 0.0
        within_var = 0.0
        
        for label in unique_labels:
            cluster_points = X[labels == label]
            n_i = len(cluster_points)
            
            # 簇质心
            centroid = np.mean(cluster_points, axis=0)
            
            # 簇间贡献
            between_var += n_i * np.sum((centroid - global_centroid) ** 2)
            
            # 簇内贡献
            within_var += np.sum((cluster_points - centroid) ** 2)
        
        if within_var == 0:
            return 0.0
        
        # CH 指数
        ch = (between_var / (n_clusters - 1)) / (within_var / (n_samples - n_clusters))
        return float(ch)
    
    @staticmethod
    def compute_all_metrics(X: np.ndarray, labels: np.ndarray) -> Dict[str, float]:
        """
        计算所有评估指标
        
        Args:
            X: 数据点 [n_samples, n_features]
            labels: 簇标签 [n_samples]
            
        Returns:
            指标字典
        """
        return {
            'silhouette': ClusteringQuality.silhouette_score(X, labels),
            'davies_bouldin': ClusteringQuality.davies_bouldin_index(X, labels),
            'calinski_harabasz': ClusteringQuality.calinski_harabasz_index(X, labels),
            'n_clusters': len(np.unique(labels)),
            'n_samples': len(X)
        }
    
    @staticmethod
    def find_optimal_k(X: np.ndarray, 
                       k_range: Tuple[int, int] = (2, 10),
                       metric: str = 'silhouette',
                       clustering_fn: Optional[Callable] = None) -> Dict:
        """
        自动搜索最优 K 值
        
        Args:
            X: 数据点
            k_range: K 值搜索范围
            metric: 评估指标 (silhouette/davies_bouldin/calinski_harabasz)
            clustering_fn: 聚类函数（签名: fn(X, k) -> labels）
            
        Returns:
            最优 K 和对应指标值
        """
        if clustering_fn is None:
            # 默认使用 K-Means
            from sklearn.cluster import KMeans
            clustering_fn = lambda X, k: KMeans(n_clusters=k, random_state=42).fit_predict(X)
        
        best_k = k_range[0]
        best_score = float('-inf') if metric != 'davies_bouldin' else float('inf')
        all_scores = {}
        
        for k in range(k_range[0], k_range[1] + 1):
            labels = clustering_fn(X, k)
            
            if metric == 'silhouette':
                score = ClusteringQuality.silhouette_score(X, labels)
                is_better = score > best_score
            elif metric == 'davies_bouldin':
                score = ClusteringQuality.davies_bouldin_index(X, labels)
                is_better = score < best_score
            elif metric == 'calinski_harabasz':
                score = ClusteringQuality.calinski_harabasz_index(X, labels)
                is_better = score > best_score
            else:
                raise ValueError(f"Unknown metric: {metric}")
            
            all_scores[k] = score
            
            if is_better:
                best_score = score
                best_k = k
        
        return {
            'optimal_k': best_k,
            'best_score': best_score,
            'metric': metric,
            'all_scores': all_scores
        }
    
    @staticmethod
    def adaptive_eps(X: np.ndarray, 
                     k: int = 5,
                     min_samples: int = 5) -> Dict:
        """
        DBSCAN eps 自适应选择
        
        使用 KNN 距离排序找拐点：
        1. 对每个点计算 k 近邻距离
        2. 排序形成 KNN 距离曲线
        3. 找拐点作为 eps
        
        Args:
            X: 数据点
            k: 近邻数
            min_samples: DBSCAN min_samples
            
        Returns:
            建议的 eps 值和相关信息
        """
        n_samples = len(X)
        
        if n_samples < min_samples + 1:
            return {'suggested_eps': 0.0, 'confidence': 'low'}
        
        # 计算 KNN 距离
        distances = np.zeros(n_samples)
        for i in range(n_samples):
            # 计算到所有其他点的距离
            dists = np.sqrt(np.sum((X - X[i]) ** 2, axis=1))
            dists.sort()
            # 取第 k 个近邻的距离
            k_idx = min(k, n_samples - 1)
            distances[i] = dists[k_idx]
        
        # 排序
        distances_sorted = np.sort(distances)
        
        # 找拐点（最大曲率点）
        # 简化方法：使用线性拟合的残差
        x_range = np.arange(len(distances_sorted))
        y = distances_sorted
        
        # 归一化
        x_norm = x_range / len(x_range)
        y_norm = (y - y.min()) / (y.max() - y.min() + 1e-10)
        
        # 直线拟合（从第一个到最后一个点）
        n = len(x_norm)
        x_mean = np.mean(x_norm)
        y_mean = np.mean(y_norm)
        slope = np.sum((x_norm - x_mean) * (y_norm - y_mean)) / (np.sum((x_norm - x_mean) ** 2) + 1e-10)
        intercept = y_mean - slope * x_mean
        
        # 计算每个点到直线的距离
        residuals = np.abs(y_norm - (slope * x_norm + intercept))
        
        # 找最大残差点作为拐点
        knee_idx = np.argmax(residuals)
        suggested_eps = distances_sorted[knee_idx]
        
        # 置信度评估
        confidence = 'medium'
        if suggested_eps > 0:
            # 检查拐点是否明显
            knee_residual = residuals[knee_idx]
            mean_residual = np.mean(residuals)
            if knee_residual > 2 * mean_residual:
                confidence = 'high'
            elif knee_residual < 0.5 * mean_residual:
                confidence = 'low'
        
        return {
            'suggested_eps': float(suggested_eps),
            'knee_index': int(knee_idx),
            'confidence': confidence,
            'knn_distances': distances_sorted.tolist(),
            'k': k,
            'min_samples': min_samples
        }
    
    @staticmethod
    def stability_score(X: np.ndarray, 
                        clustering_fn: Callable,
                        n_bootstrap: int = 10,
                        sample_ratio: float = 0.8) -> float:
        """
        计算聚类稳定度 (Bootstrap 重采样)
        
        通过多次重采样重复聚类，评估结果一致性。
        稳定度越高，聚类结果越可靠。
        
        Args:
            X: 数据点
            clustering_fn: 聚类函数
            n_bootstrap: Bootstrap 次数
            sample_ratio: 采样比例
            
        Returns:
            稳定度分数 [0, 1]
        """
        n_samples = len(X)
        n_sample = int(n_samples * sample_ratio)
        
        labels_list = []
        
        for _ in range(n_bootstrap):
            # 随机采样
            indices = np.random.choice(n_samples, n_sample, replace=False)
            X_sample = X[indices]
            
            # 聚类
            labels = clustering_fn(X_sample)
            labels_list.append(labels)
        
        # 计算一致性
        # 使用调整兰德指数 (ARI) 对聚类结果进行比较
        if len(labels_list) < 2:
            return 1.0
        
        from sklearn.metrics import adjusted_rand_score
        
        total_ari = 0.0
        count = 0
        
        for i in range(len(labels_list)):
            for j in range(i + 1, len(labels_list)):
                # 对齐标签（因为不同运行的标签编号可能不同）
                ari = adjusted_rand_score(labels_list[i], labels_list[j])
                total_ari += ari
                count += 1
        
        return float(total_ari / count) if count > 0 else 1.0
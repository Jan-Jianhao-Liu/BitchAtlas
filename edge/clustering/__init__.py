"""
BirchAtlas - BIRCH 流式聚类算法库
====================================

基于 BIRCH (Balanced Iterative Reducing and Clustering using Hierarchies) 算法的在线流式聚类实现。

核心数据结构：
    CF (Clustering Feature) = (N, LS, SS)
    - N: 簇中点数
    - LS: 线性求和 (各维度)
    - SS: 平方和 (各维度)

特点：
    1. CF 树在线插入复杂度 O(log n)
    2. 内存占用固定
    3. 支持增量更新和序列化
    4. 支持云端 CF 树合并

参考文献：
    Zhang, T., Ramakrishnan, R., & Livny, M. (1996).
    BIRCH: an efficient data clustering method for very large databases.
    SIGMOD Record, 25(2), 103-114.
"""

from .cf import CF, CFNode
from .birch_tree import BirchTree
from .outlier_detector import OutlierDetector
from .cf_serializer import CFSerializer
from .quality_metrics import ClusteringQuality

__version__ = "0.1.0"
__all__ = [
    "CF",
    "CFNode", 
    "BirchTree",
    "OutlierDetector",
    "CFSerializer",
    "ClusteringQuality",
]
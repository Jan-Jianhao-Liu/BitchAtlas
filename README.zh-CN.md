<div align="center">

# BirchAtlas 桦聚图集

**边缘流式聚类，云端全景图集**

*面向施工质检的首个开源边缘-云端协同聚类平台*

**钢筋间距检测 · 边缘 AI · 流式聚类 · BIRCH · MQTT · Jetson · TensorRT**

[![Go](https://img.shields.io/badge/Go-1.22-00ADD8?logo=go&logoColor=white)](https://golang.org)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Vue](https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white)](https://vuejs.org)
[![ROS2](https://img.shields.io/badge/ROS2-Humble-22314E?logo=ros&logoColor=white)](https://docs.ros.org)
[![TensorRT](https://img.shields.io/badge/TensorRT-8.x-76B900?logo=nvidia&logoColor=white)](https://developer.nvidia.com/tensorrt)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**语言**: [English](README.md) · [简体中文](README.zh-CN.md)

</div>

---

## 为什么做 BirchAtlas

施工现场的钢筋间距检测长期依赖人工，缺少"检测 → 数据管理 → 云端分析 → 设备运维"的完整闭环。

**BirchAtlas 填补的缺口**：一个把**钢筋间距智能检测**（场景入口）与**边缘-云端流式聚类平台**（技术内核）结合的完整开源方案——现场边缘网关实时检测 + BIRCH 流式聚类识别离群测量，云端全景聚类做质量分区，MQTT 设备影子 + A/B 分区 OTA 支撑远程运维。

## 核心特性

- **边缘-云端协同流式聚类**：BIRCH（SIGMOD 1996 经典流式聚类算法）CF 树在边缘实时聚类，CF 向量序列化后增量合并到云端全局模型——"边聚类、云融合"
- **算法即插即用（AaaS）**：标准化算法包（manifest + 模型 + 自检探针），沙箱验证后灰度热加载，不合格自动回退
- **A/B 双分区原子 OTA**：升级写入备用分区 → 自检 → 切换，失败自动回滚，业务零中断
- **云原生微服务**：Go 微服务 + K8s + EMQX(MQTT 5.0)，支持水平扩展与边缘海量接入
- **聚类质量评估闭环**：轮廓系数 / DBI / CH 指数驱动参数自优化（K 搜索、eps 自适应）
- **全链路可观测**：OpenTelemetry 分布式追踪 + 边缘 GPU/温度/推理耗时遥测
- **一机一密安全体系**：设备证书双向 TLS + 指令签名 + 算法包验签

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│  终端用户层  Web 控制台 (Vue3) │ 可视化大屏 │ Open API        │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTPS
┌──────────────────────────────▼───────────────────────────────┐
│  云端微服务层 (Go · K8s)                                      │
│  auth · device · project · algo · task · ingest · cluster ·  │
│  alert ── EMQX / Kafka / PostgreSQL / ClickHouse / MinIO     │
└──────────────────────────────┬───────────────────────────────┘
                               │ MQTT 5.0 over TLS（4G/5G）
┌──────────────────────────────▼───────────────────────────────┐
│  边缘智能网关层 (Jetson Orin NX)                              │
│  EdgeGateway (Go) │ Inference (TensorRT) │ 流式聚类 (BIRCH)  │
│  └── ROS2 Humble (DDS) 局域网通信 ──┐                        │
└─────────────────────────────────────┼────────────────────────┘
                                      │ Wi-Fi
┌─────────────────────────────────────▼────────────────────────┐
│  采集控制层  钢筋间距检测装置 │ 图像采集 │ 传感器             │
└──────────────────────────────────────────────────────────────┘
```

## 聚类算法引擎

```
测量值流 ──▶ 边缘在线聚类 (BIRCH CF树 / Online DBSCAN) ──CF树增量合并──▶
                                                                      ▼
        ◀── 参数自优化反馈 ◀── 质量评估(轮廓/DBI/CH) ◀── 云端离线聚类
                                                          (K-Means/GMM/DBSCAN/层次)
```

| 场景 | 算法 | 产出 |
|---|---|---|
| 测量值离群识别 | 边缘流式 BIRCH / Online DBSCAN | 实时标注可疑测量点 |
| 楼板质量分区 | 云端 K-Means++ / GMM | 区域质量热力图 |
| 施工工艺分类 | 层次聚类 + 轮廓分析 | 施工模式分组 |
| 异常趋势发现 | 时间序列聚类（DTW+K-Means） | 异常时段/位置 |
| 模型漂移检测 | 聚类分布对比（JS 散度） | 提示模型重训 |

## 快速开始（Docker Compose）

```bash
# 1. 克隆仓库
git clone https://github.com/Jan-Jianhao-Liu/BitchAtlas.git
cd BitchAtlas

# 2. 拉起云端全栈（EMQX/PG/CH/Redis/MinIO/Kafka + 微服务）
docker compose up -d

# 3. 启动边缘网关模拟器（随机生成钢筋间距检测数据）
make edge-sim

# 4. 打开控制台 → 观察设备上线 → 下发检测指令 → 数据入湖 → 创建聚类任务
open http://localhost:8080
```

## Demo 演示

- **工程质检演示**：上传楼板钢筋照片 → 边缘检测钢筋 → 间距测量 → 聚类分区热力图（质量等级 A/B/C/D + 离群点高亮）
- **算法演示**（`examples/notebooks/`）：Jupyter 交互展示 BIRCH CF 树边缘聚类 → 云端增量合并全过程，配合钢筋间距数据集

## 仓库结构

```
birchatlas/
├── cloud/       # 云端微服务 (Go)
├── edge/        # 边缘网关与聚类 (Go/Python)
├── web/         # Web 控制台 (Vue3)
├── proto/       # Protobuf 协议定义
├── deploy/      # Helm Charts / docker-compose
├── docs/        # 架构/MQTT协议/API/部署文档
├── examples/    # edge-sim 模拟器 + 示例数据集 + Jupyter 演示
└── .github/     # CI/CD (GitHub Actions)
```

## 技术栈

| 端 | 技术 |
|---|---|
| 云端 | Go · Python(FastAPI) · Kubernetes · EMQX 5 · Kafka · PostgreSQL · ClickHouse · Redis · MinIO · Keycloak |
| 边缘 | Jetson Orin NX · Ubuntu 22.04 · ROS2 Humble · TensorRT 8 · ONNX Runtime · Go |
| 前端 | Vue 3 · TypeScript · Vite · ECharts · Pinia |
| 可观测 | OpenTelemetry · Prometheus · Grafana · Loki · Jaeger |

## 文档

- [工程重构方案](大数据聚类算法应用系统_V2.0_工程重构方案.md)
- [聚类算法设计](docs/clustering-algorithm.md)
- [MQTT 协议规范](docs/mqtt-protocol.md)
- [API 规范](docs/api/)
- [部署指南](docs/deployment/)

## 贡献

欢迎提交 Issue 与 PR。请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md)。

## License

[MIT](LICENSE) © BirchAtlas Contributors

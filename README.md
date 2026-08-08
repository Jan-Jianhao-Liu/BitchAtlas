<div align="center">

# BirchAtlas

**Streaming clustering at the edge, unified atlas in the cloud.**

*The first open-source edge-cloud collaborative clustering platform for construction quality inspection*

**rebar spacing detection · edge AI · streaming clustering · BIRCH · MQTT · Jetson · TensorRT**

[![Go](https://img.shields.io/badge/Go-1.22-00ADD8?logo=go&logoColor=white)](https://golang.org)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Vue](https://img.shields.io/badge/Vue-3-4FC08D?logo=vuedotjs&logoColor=white)](https://vuejs.org)
[![ROS2](https://img.shields.io/badge/ROS2-Humble-22314E?logo=ros&logoColor=white)](https://docs.ros.org)
[![TensorRT](https://img.shields.io/badge/TensorRT-8.x-76B900?logo=nvidia&logoColor=white)](https://developer.nvidia.com/tensorrt)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Languages**: [English](README.md) · [简体中文](README.zh-CN.md)

</div>

---

## Why BirchAtlas

Rebar spacing inspection on construction sites has long relied on manual labor, lacking a closed loop of "detection → data management → cloud analysis → device maintenance."

**BirchAtlas fills the gap** by combining **intelligent rebar spacing detection** (the scenario entry point) with an **edge-cloud streaming clustering platform** (the technical core). Edge gateways perform real-time detection and BIRCH streaming clustering to identify outlier measurements on-site, while the cloud builds panoramic clusters for quality zoning. MQTT device shadows and A/B partition OTA support remote device operations.

## Key Features

- **Edge-Cloud Collaborative Streaming Clustering**: BIRCH (SIGMOD 1996) CF trees cluster in real-time at the edge; CF vectors are serialized and incrementally merged into a global cloud model — "cluster at the edge, fuse in the cloud."
- **Algorithm-as-a-Service (AaaS)**: Standardized algorithm packages (manifest + model + self-check probes) with sandbox validation, grayscale rollout, and automatic rollback.
- **A/B Dual-Partition Atomic OTA**: Write to backup partition → self-check → switch. Automatic rollback on failure with zero business interruption.
- **Cloud-Native Microservices**: Go microservices + Kubernetes + EMQX (MQTT 5.0) for horizontal scaling and massive edge connectivity.
- **Clustering Quality Evaluation Loop**: Silhouette score / DBI / CH index drive parameter auto-optimization (K search, eps adaptation).
- **Full-Stack Observability**: OpenTelemetry distributed tracing + edge GPU/temperature/inference latency telemetry.
- **Per-Device Security**: Mutual TLS with device certificates + command signing + algorithm package signature verification.

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  User Layer      Web Console (Vue3) │ Dashboard │ Open API   │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTPS
┌──────────────────────────────▼───────────────────────────────┐
│  Cloud Microservices (Go · K8s)                              │
│  auth · device · project · algo · task · ingest · cluster ·  │
│  alert ── EMQX / Kafka / PostgreSQL / ClickHouse / MinIO     │
└──────────────────────────────┬───────────────────────────────┘
                               │ MQTT 5.0 over TLS (4G/5G)
┌──────────────────────────────▼───────────────────────────────┐
│  Edge Gateway (Jetson Orin NX)                               │
│  EdgeGateway (Go) │ Inference (TensorRT) │ Streaming (BIRCH) │
│  └── ROS2 Humble (DDS) LAN ──┐                               │
└──────────────────────────────┼───────────────────────────────┘
                               │ Wi-Fi
┌──────────────────────────────▼───────────────────────────────┐
│  Collection Layer  Rebar Spacing Detector │ Camera │ Sensors  │
└──────────────────────────────────────────────────────────────┘
```

## Clustering Engine

```
Measurement Stream ──▶ Edge Online Clustering (BIRCH CF-Tree / Online DBSCAN) ──CF-Tree Merge──▶
                                                                                               ▼
        ◀── Parameter Auto-Opt Feedback ◀── Quality Eval (Silhouette/DBI/CH) ◀── Cloud Offline
                                                                                (K-Means/GMM/DBSCAN/Hierarchical)
```

| Scenario | Algorithm | Output |
|---|---|---|
| Outlier measurement detection | Edge streaming BIRCH / Online DBSCAN | Real-time flagging of suspicious points |
| Slab quality zoning | Cloud K-Means++ / GMM | Regional quality heatmap |
| Construction process classification | Hierarchical clustering + silhouette analysis | Construction pattern groups |
| Anomaly trend discovery | Time-series clustering (DTW + K-Means) | Anomalous periods/locations |
| Model drift detection | Cluster distribution comparison (JS divergence) | Model retraining alerts |

## Quick Start (Docker Compose)

```bash
# 1. Clone the repository
git clone https://github.com/Jan-Jianhao-Liu/BitchAtlas.git
cd BitchAtlas

# 2. Launch the cloud stack (EMQX/PG/CH/Redis/MinIO/Kafka + microservices)
docker compose up -d

# 3. Start the edge gateway simulator (generates synthetic rebar spacing data)
make edge-sim

# 4. Open the console → observe device online → send detection command → data ingestion → create clustering job
open http://localhost:8080
```

## Demo

- **Quality Inspection Demo**: Upload slab rebar photos → edge detection → spacing measurement → clustering zoning heatmap (quality grades A/B/C/D + outlier highlighting)
- **Algorithm Demo** (`examples/notebooks/`): Jupyter interactive walkthrough of BIRCH CF-tree edge clustering → cloud incremental merge, with a rebar spacing dataset

## Repository Structure

```
birchatlas/
├── cloud/       # Cloud microservices (Go)
├── edge/        # Edge gateway & clustering (Go/Python)
├── web/         # Web console (Vue3)
├── proto/       # Protobuf definitions
├── deploy/      # Helm Charts / docker-compose
├── docs/        # Architecture / MQTT protocol / API / deployment docs
├── examples/    # edge-sim simulator + datasets + Jupyter demos
└── .github/     # CI/CD (GitHub Actions)
```

## Tech Stack

| Layer | Technologies |
|---|---|
| Cloud | Go · Python (FastAPI) · Kubernetes · EMQX 5 · Kafka · PostgreSQL · ClickHouse · Redis · MinIO · Keycloak |
| Edge | Jetson Orin NX · Ubuntu 22.04 · ROS2 Humble · TensorRT 8 · ONNX Runtime · Go |
| Frontend | Vue 3 · TypeScript · Vite · ECharts · Pinia |
| Observability | OpenTelemetry · Prometheus · Grafana · Loki · Jaeger |

## Documentation

- [Engineering Plan](大数据聚类算法应用系统_V2.0_工程重构方案.md) (Chinese)
- [Clustering Algorithm Design](docs/clustering-algorithm.md)
- [MQTT Protocol Spec](docs/mqtt-protocol.md)
- [API Reference](docs/api/)
- [Deployment Guide](docs/deployment/)

## Contributing

Issues and PRs are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © BirchAtlas Contributors

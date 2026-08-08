# Cluster Service Dockerfile
FROM golang:1.22-alpine AS builder

WORKDIR /app

# 安装 SQLite 依赖
RUN apk add --no-cache gcc musl-dev sqlite-dev

# 复制 Go 模块文件
COPY cloud/cluster-svc/go.mod .
COPY cloud/cluster-svc/go.sum .

# 下载依赖
RUN go mod download

# 复制源代码
COPY cloud/cluster-svc/ .

# 构建
RUN CGO_ENABLED=1 go build -o cluster-svc .

# 运行时镜像
FROM alpine:3.19

# 安装 SQLite 运行时
RUN apk add --no-cache sqlite-libs ca-certificates

WORKDIR /app

# 复制二进制
COPY --from=builder /app/cluster-svc .

# 创建数据目录
RUN mkdir -p /app/data

# 暴露端口
EXPOSE 8007

# 启动
CMD ["./cluster-svc"]
# Device Service Dockerfile
FROM golang:1.22-alpine AS builder

WORKDIR /app

# 复制 Go 模块文件
COPY cloud/device-svc/go.mod .

# 下载依赖（若 go.sum 不存在会自动生成）
RUN go mod download

# 复制源代码
COPY cloud/device-svc/ .

# 构建（纯 Go，无 CGO 依赖）
RUN CGO_ENABLED=0 GOOS=linux go build -o device-svc .

# 运行时镜像
FROM alpine:3.19

# 安装基础证书
RUN apk add --no-cache ca-certificates

WORKDIR /app

# 复制二进制
COPY --from=builder /app/device-svc .

# 暴露端口
EXPOSE 8002

# 启动
CMD ["./device-svc"]

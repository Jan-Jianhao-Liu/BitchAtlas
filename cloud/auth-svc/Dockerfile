# Auth Service Dockerfile
FROM golang:1.22-alpine AS builder

WORKDIR /app

# 先复制 go.mod 以利用层缓存下载依赖
COPY cloud/auth-svc/go.mod ./

# 下载依赖（go.sum 不存在时会自动生成并校验）
RUN go mod download

# 复制源代码
COPY cloud/auth-svc/ ./

# 构建（纯 Go，无需 CGO，静态编译）
RUN CGO_ENABLED=0 GOOS=linux go build -o auth-svc .

# 运行时镜像
FROM alpine:3.19

# 安装 CA 证书（HTTPS 调用需要）
RUN apk add --no-cache ca-certificates

WORKDIR /app

# 复制二进制
COPY --from=builder /app/auth-svc .

# 暴露端口
EXPOSE 8001

# 启动
CMD ["./auth-svc"]

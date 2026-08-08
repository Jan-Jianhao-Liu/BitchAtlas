# Web Console Dockerfile
FROM node:18-alpine AS builder

WORKDIR /app

# 复制依赖文件
COPY web/package.json .
COPY web/package-lock.json* ./

# 安装依赖
RUN npm install

# 复制源代码
COPY web/ .

# 构建
RUN npm run build

# 运行时镜像
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY web/nginx.conf /etc/nginx/conf.d/default.conf

# 暴露端口
EXPOSE 80

# 启动
CMD ["nginx", "-g", "daemon off;"]
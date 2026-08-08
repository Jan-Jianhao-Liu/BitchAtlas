FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY examples/edge-sim/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY edge/ edge/
COPY examples/edge-sim/ examples/edge-sim/

# 创建数据目录
RUN mkdir -p /app/data

# 默认运行演示模式
CMD ["python", "examples/edge-sim/main.py", "--mode", "demo", "--duration", "60"]
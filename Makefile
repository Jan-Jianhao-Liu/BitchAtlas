.PHONY: help start stop build test edge-sim clean

# 变量定义
COMPOSE_FILE := deploy/docker-compose.yml
GO := go
PYTHON := python3
NPM := npm

# 默认目标
help: ## 显示帮助信息
	@echo "BirchAtlas 桦聚图集 - 边缘-云端流式聚类平台"
	@echo ""
	@echo "用法:"
	@echo "  make start         启动云端全栈服务 (Docker Compose)"
	@echo "  make stop          停止所有服务"
	@echo "  make build         构建所有微服务"
	@echo "  make test          运行测试"
	@echo "  make edge-sim      启动边缘网关模拟器"
	@echo "  make web-dev       启动 Web 开发服务器"
	@echo "  make clean         清理所有服务和数据卷"
	@echo ""

# 启动云端全栈
start: ## 启动云端全栈服务
	docker compose -f $(COMPOSE_FILE) up -d
	@echo "服务已启动，访问 http://localhost:8080"

# 停止服务
stop: ## 停止所有服务
	docker compose -f $(COMPOSE_FILE) down

# 构建所有服务
build: build-cloud build-edge ## 构建所有微服务

build-cloud: ## 构建云端微服务
	@for dir in cloud/*/; do \
		if [ -f "$$dir/go.mod" ]; then \
			echo "Building $$dir..."; \
			cd $$dir && $(GO) build ./... && cd ../..; \
		fi; \
	done

build-edge: ## 构建边缘模块
	@for dir in edge/*/; do \
		if [ -f "$$dir/requirements.txt" ]; then \
			echo "Installing $$dir..."; \
			cd $$dir && $(PYTHON) -m pip install -r requirements.txt && cd ../..; \
		fi; \
	done

# 运行测试
test: test-cloud test-edge ## 运行所有测试

test-cloud: ## 运行云端测试
	@for dir in cloud/*/; do \
		if [ -f "$$dir/go.mod" ]; then \
			echo "Testing $$dir..."; \
			cd $$dir && $(GO) test ./... && cd ../..; \
		fi; \
	done

test-edge: ## 运行边缘测试
	@for dir in edge/*/; do \
		if [ -f "$$dir/pytest.ini" ] || [ -f "$$dir/setup.py" ]; then \
			echo "Testing $$dir..."; \
			cd $$dir && $(PYTHON) -m pytest && cd ../..; \
		fi; \
	done

# 边缘模拟器
edge-sim: ## 启动边缘网关模拟器
	cd examples/edge-sim && $(PYTHON) main.py

# Web 开发
web-dev: ## 启动 Web 开发服务器
	cd web && $(NPM) install && $(NPM) run dev

# 清理
clean: ## 清理所有服务和数据卷
	docker compose -f $(COMPOSE_FILE) down -v
	@echo "已清理所有服务和数据卷"

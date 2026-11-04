# qclub-odoo —— 统一命令入口
# 需要：GNU make、Docker（含 compose v2）、Python 3。Windows 请在 WSL2 的 Ubuntu 中使用。
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

COMPOSE := docker compose -f docker/docker-compose.test.yml
MODULE  := qclub_billiard
BASE_DB := qclub_base
DB      ?= qclub_test
REPORTS := docs/reports
PSQL    := $(COMPOSE) exec -T db psql -U odoo -v ON_ERROR_STOP=1
ODOO    := $(COMPOSE) run --rm -T odoo odoo

.DEFAULT_GOAL := help
.PHONY: help guard up base test e2e lint report shell down reset

help:
	@echo "make up      启动测试数据库，并在首次运行时构建基础模板库（几分钟）"
	@echo "make test    重建测试库、安装模块、运行单元测试，输出 JUnit XML"
	@echo "make e2e     运行浏览器端到端测试（阶段 2 起）"
	@echo "make lint    代码检查"
	@echo "make report  生成测试报告与需求覆盖对照表"
	@echo "make shell   进入测试库的 Odoo shell"
	@echo "make down    停止环境（保留数据）"
	@echo "make reset   销毁环境和全部数据，从零重建"

# 安全护栏：只允许操作以 qclub_ 开头的测试库，绝不能碰生产库 AUSHARE
guard:
	@case "$(DB)" in qclub_*) ;; *) echo "REFUSED: DB 必须以 qclub_ 开头，且绝不能是生产库 AUSHARE（当前: $(DB)）"; exit 1;; esac

up: guard
	$(COMPOSE) up -d --wait db
	@if $(PSQL) -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$(BASE_DB)'" | grep -q 1; then echo "基础模板库 $(BASE_DB) 已存在"; else $(MAKE) base; fi

# 构建基础模板库：安装依赖模块 + 启用 btree_gist + 创建 AUSHARE / Q Club 两个测试网站
base: guard
	$(COMPOSE) up -d --wait db
	$(PSQL) -d postgres -c "DROP DATABASE IF EXISTS $(BASE_DB) WITH (FORCE)" -c "CREATE DATABASE $(BASE_DB) ENCODING 'UTF8' TEMPLATE template0"
	$(PSQL) -d $(BASE_DB) -c "CREATE EXTENSION IF NOT EXISTS btree_gist"
	$(ODOO) -d $(BASE_DB) -i website_sale,portal,bus,mail --without-demo=True --stop-after-init
	$(ODOO) shell -d $(BASE_DB) --no-http < docker/seed_websites.py

test: guard up
	mkdir -p $(REPORTS)
	$(PSQL) -d postgres -c "DROP DATABASE IF EXISTS $(DB) WITH (FORCE)" -c "CREATE DATABASE $(DB) TEMPLATE $(BASE_DB)"
	$(ODOO) -d $(DB) -i $(MODULE) --test-enable --test-tags /$(MODULE) --stop-after-init --without-demo=True --log-level=test 2>&1 | tee $(REPORTS)/odoo-test.log || true
	python3 tools/odoo_log_to_junit.py $(REPORTS)/odoo-test.log $(REPORTS)/junit.xml

e2e: guard
	@if [ ! -f e2e/package.json ]; then echo "e2e 尚未建立（阶段 2 开始），跳过"; exit 0; fi; \
	cd e2e && npm ci && npx playwright test

lint:
	docker run --rm -v "$(CURDIR)":/io -w /io ghcr.io/astral-sh/ruff:latest check addons tools

report:
	python3 tools/make_report.py

shell: guard
	$(COMPOSE) run --rm odoo odoo shell -d $(DB) --no-http

down:
	$(COMPOSE) down

reset:
	$(COMPOSE) down -v

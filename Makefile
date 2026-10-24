# Common tasks. Run `make help` to list them.
.DEFAULT_GOAL := help
PROJECT ?= examples/jaffle_shop

.PHONY: help install dev dev-api dev-web lint format typecheck test build docker up down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install Python and web dependencies
	uv sync
	pnpm install
	uv run pre-commit install

dev: ## Run the API and the web dev server together (PROJECT=path/to/dbt)
	@trap 'kill 0' INT TERM; \
	  uv run openpipeline serve $(PROJECT) --reload & \
	  pnpm dev & \
	  wait

dev-api: ## Run only the API, reloading on code changes
	uv run openpipeline serve $(PROJECT) --reload

dev-web: ## Run only the web dev server (proxies /api to :8484)
	pnpm dev

lint: ## Lint Python and web code
	uv run ruff check .
	uv run ruff format --check .
	pnpm lint

format: ## Auto-format everything
	uv run ruff check --fix .
	uv run ruff format .
	pnpm --filter @openpipeline/web format

typecheck: ## Type-check Python and web code
	uv run mypy
	pnpm typecheck

test: ## Run all tests
	uv run pytest --cov
	pnpm test

build: ## Build the web UI into the Python package, then build wheels
	pnpm build
	uv build --package openpipeline-core --out-dir dist
	uv build --package openpipeline --out-dir dist

docker: ## Build the Docker image
	docker build -t openpipeline:dev .

up: ## Start the UI and MCP server with Docker Compose
	docker compose up --build

down: ## Stop Docker Compose
	docker compose down

clean: ## Remove build output and caches
	rm -rf dist apps/server/src/openpipeline/static .pytest_cache .mypy_cache .ruff_cache .coverage

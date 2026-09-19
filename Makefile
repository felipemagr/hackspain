.DEFAULT_GOAL := help
.PHONY: help install inspect clean-data cash panel pipeline mock sql notebook docker-build docker-pipeline \
        api api-up api-down slack-test context test test-quick lint format quality ci clean

RAW_DIR ?= data/raw
PROCESSED_DIR := data/processed
MARTS_DIR := data/marts
CLEAN_STAMP := $(PROCESSED_DIR)/.clean.stamp
CASH := $(MARTS_DIR)/cash_monthly.parquet
PANEL := $(MARTS_DIR)/panel_group.parquet
IMAGE ?= xray:latest

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

# Setup
install: ## Install dependencies and the notebook output stripper
	uv sync
	uv run nbstripout --install

# Data
inspect: ## Print shape and dtypes of every CSV in data/raw
	uv run python -m xray.pipeline.data

$(CLEAN_STAMP): $(wildcard $(RAW_DIR)/*.csv) src/xray/pipeline/clean.py
	uv run python -m xray.pipeline.clean
	@touch $@

$(CASH): $(CLEAN_STAMP) src/xray/pipeline/cash.py
	uv run python -m xray.pipeline.cash

$(PANEL): $(CASH) src/xray/pipeline/panel.py
	uv run python -m xray.pipeline.panel

clean-data: $(CLEAN_STAMP) ## Stage data/raw as parquet in data/processed

cash: $(CASH) ## Reconstruct the monthly cash mart

panel: $(PANEL) ## Build the monthly panel mart, rebuilding upstream layers as needed

pipeline: ## Rebuild everything from the raw CSVs, ignoring what is already built
	uv run python -m xray.pipeline

mock: ## Write invented serving tables to data/serving so the product can be built before the score
	uv run python -m xray.scoring.mock

# Docker
docker-build: ## Build the pipeline image
	docker build -t $(IMAGE) .

docker-pipeline: ## Run the pipeline in Docker over ./data/raw
	docker run --rm \
		-v "$(PWD)/$(RAW_DIR):/data/raw:ro" \
		-v "$(PWD)/$(PROCESSED_DIR):/data/processed" \
		-v "$(PWD)/$(MARTS_DIR):/data/marts" \
		$(IMAGE)

sql: ## Open a DuckDB shell with views over the marts
	duckdb -init .duckdbrc

notebook: ## Register the project venv as a Jupyter kernel
	uv run python -m ipykernel install --user --name xray --display-name "xray"

# API
api: ## Run the API locally with reload on http://localhost:8000
	uv run uvicorn xray.api.main:app --reload

api-up: ## Start the API container in the background
	docker compose up -d --build

api-down: ## Stop the API container
	docker compose down

slack-test: ## Send a test alert to the Slack webhook in .env
	uv run python -m xray.integrations.slack

# Agents
context: ## Public context for one company, cached in data/serving/context: make context NAME="Cabify" [REFRESH=1]
	uv run python -m xray.agents.context_retrieval $(if $(REFRESH),--refresh) "$(NAME)"

# Tests
test: ## Run all tests
	uv run pytest -q

test-quick: ## Run tests, stop at the first failure
	uv run pytest -q -x --ff

# Code quality
lint: ## Lint without changing files
	uv run ruff check .

format: ## Autofix lint issues and format
	uv run ruff check --fix .
	uv run ruff format .

quality: lint ## Lint and check formatting
	uv run ruff format --check .

ci: quality test ## Everything that must pass before pushing

# Housekeeping
clean: ## Remove caches and build leftovers
	rm -rf .pytest_cache .ruff_cache build dist
	find . -type d -name __pycache__ -not -path "./.venv/*" -prune -exec rm -rf {} +

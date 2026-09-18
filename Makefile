.DEFAULT_GOAL := help
.PHONY: help install inspect clean-data cash panel pipeline sql notebook docker-build docker-pipeline \
        test test-quick lint format quality ci clean

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
	uv run python -m xray.data

$(CLEAN_STAMP): $(wildcard $(RAW_DIR)/*.csv) src/xray/clean.py
	uv run python -m xray.clean
	@touch $@

$(CASH): $(CLEAN_STAMP) src/xray/cash.py
	uv run python -m xray.cash

$(PANEL): $(CASH) src/xray/panel.py
	uv run python -m xray.panel

clean-data: $(CLEAN_STAMP) ## Stage data/raw as parquet in data/processed

cash: $(CASH) ## Reconstruct the monthly cash mart

panel: $(PANEL) ## Build the monthly panel mart, rebuilding upstream layers as needed

pipeline: ## Rebuild everything from the raw CSVs, ignoring what is already built
	uv run python -m xray.pipeline

# Docker
docker-build: ## Build the pipeline image
	docker build -t $(IMAGE) .

docker-pipeline: ## Run the pipeline in Docker over ./data/raw
	docker run --rm \
		-v "$(PWD)/$(RAW_DIR):/data/raw:ro" \
		-v "$(PWD)/$(PROCESSED_DIR):/data/processed" \
		$(IMAGE)

sql: ## Open a DuckDB shell with views over the marts
	duckdb -init .duckdbrc

notebook: ## Register the project venv as a Jupyter kernel
	uv run python -m ipykernel install --user --name xray --display-name "xray"

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

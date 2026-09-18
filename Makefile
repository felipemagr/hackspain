.DEFAULT_GOAL := help
.PHONY: help install inspect notebook test test-quick lint format quality ci clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

# Setup
install: ## Install dependencies and the notebook output stripper
	uv sync
	uv run nbstripout --install

# Data
inspect: ## Print shape and dtypes of every CSV in data/raw
	uv run python -m xray.data

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

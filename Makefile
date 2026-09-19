.DEFAULT_GOAL := help
.PHONY: fx help install inspect clean-data cash panel pipeline mock sql notebook docker-build docker-pipeline \
        events score score-baseline validate monitor alerts notify serve submit api api-up api-down slack-test email-test \
        context peers test test-quick lint format quality ci clean web-install web-data web \
        web-build publish

RAW_DIR ?= data/raw
PROCESSED_DIR := data/processed
MARTS_DIR := data/marts
CLEAN_STAMP := $(PROCESSED_DIR)/.clean.stamp
CASH := $(MARTS_DIR)/cash_monthly.parquet
PANEL := $(MARTS_DIR)/panel_group.parquet
BASELINE_SCORE := $(MARTS_DIR)/real_scores.parquet
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

$(BASELINE_SCORE): $(PANEL) src/xray/scoring/score_baseline.py
	uv run python -m xray.scoring.score_baseline

clean-data: $(CLEAN_STAMP) ## Stage data/raw as parquet in data/processed

cash: $(CASH) ## Reconstruct the monthly cash mart

panel: $(PANEL) ## Build the monthly panel mart, rebuilding upstream layers as needed

fx: ## Refresh the yearly euro rates (ECB, pegs, the data) in src/xray/pipeline/fx_rates.csv
	uv run python -m xray.pipeline.fx

pipeline: ## Rebuild everything from the raw CSVs, ignoring what is already built
	uv run python -m xray.pipeline

EVENTS := $(MARTS_DIR)/events.parquet
SCORES := $(MARTS_DIR)/scores.parquet

$(EVENTS): $(PANEL) src/xray/scoring/events.py
	uv run python -m xray.scoring.events

$(SCORES): $(PANEL) src/xray/scoring/score.py src/xray/scoring/anchors.py
	uv run python -m xray.scoring.score

events: $(EVENTS) ## Build the proxy distress labels used to calibrate and validate the score

score: $(SCORES) ## Score every group-month from the panel

score-baseline: $(BASELINE_SCORE) ## Calculate provisional group scores for the internal viewer

validate: $(SCORES) $(EVENTS) ## Discrimination, trajectory, stability and ablation, split by group
	uv run python -m xray.scoring.validate

ALERTS := $(MARTS_DIR)/alerts.parquet

$(ALERTS): $(SCORES) src/xray/scoring/monitor.py src/xray/scoring/trend.py
	uv run python -m xray.scoring.monitor

monitor: $(ALERTS) ## Detect jumps and sustained shifts in the score, write the alert feed

alerts: $(ALERTS) ## Show the alerts not yet sent, send nothing: make alerts [MONTH=2026-05]
	uv run python -m xray.scoring.notify --dry-run $(if $(MONTH),--month $(MONTH))

notify: $(ALERTS) ## Send the pending alerts: make notify [MONTH=2026-05] [CHANNEL=slack|email]
	uv run python -m xray.scoring.notify --channel $(or $(CHANNEL),slack) $(if $(MONTH),--month $(MONTH))

serve: $(PANEL) ## Write the real serving tables (scores, drivers, alerts, offers, actions, payers) to data/serving
	uv run python -m xray.scoring.serve
	uv run python -m xray.scoring.payers

submit: ## Score a hidden-test dump end to end: make submit RAW=path/to/csvs [OUT=submission]
	uv run python -m xray.scoring.submit --raw-dir $(RAW) --out $(or $(OUT),submission)

mock: ## Write invented serving tables to data/serving so the product can be built before the score
	uv run python -m xray.scoring.mock

# Docker
docker-build: ## Build the pipeline image
	docker build --target pipeline -t $(IMAGE) .

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

email-test: ## Send a test alert to the SMTP host in .env
	uv run python -m xray.integrations.email

# Web demo
web-install: ## Install the demo front end dependencies
	cd web && npm install

web-data: ## Export data/serving parquet to web/public/data as JSON for the front end
	uv run python -m xray.pipeline.export_serving

web: web-data ## Run the demo front end on http://localhost:5173
	cd web && npm run dev

web-build: web-data ## Build the demo front end into web/dist
	cd web && npm run build

publish: web-data ## Stage everything Render serves (tables, JSON copies, agent cache): commit and push after
	git add data/serving/*.parquet data/serving/context web/public/data
	git status --short data/serving web/public/data

# Agents
context: ## Public context for one company, cached in data/serving/context: make context NAME="Cabify" [REFRESH=1]
	uv run python -m xray.agents.context_retrieval $(if $(REFRESH),--refresh) "$(NAME)"

peers: ## Sector read from a company's competitors, cached in data/serving/context: make peers NAME="Cabify" [REFRESH=1]
	uv run python -m xray.agents.peers $(if $(REFRESH),--refresh) "$(NAME)"

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

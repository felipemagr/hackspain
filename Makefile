.DEFAULT_GOAL := help
.PHONY: fx help install inspect clean-data cash panel pipeline mock sql notebook docker-build docker-pipeline \
        events score score-baseline validate monitor alerts notify serve submit replay demo demo-data \
        lighthouse lighthouse-down api api-up api-down slack-test email-test \
        context peers test test-quick lint format quality ci clean macro web-install web-data web \
        web-build publish

RAW_DIR ?= data/raw
PROCESSED_DIR := data/processed
MARTS_DIR := data/marts
CLEAN_STAMP := $(PROCESSED_DIR)/.clean.stamp
CASH := $(MARTS_DIR)/cash_monthly.parquet
PANEL := $(MARTS_DIR)/panel_group.parquet
BASELINE_SCORE := $(MARTS_DIR)/real_scores.parquet
IMAGE ?= xray:latest
API_PORT ?= 8000
WEB_PORT ?= 5173
WEB_DEPS := web/node_modules/.package-lock.json

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
	@test -n "$(wildcard $(RAW_DIR)/*.csv)" || { \
		echo "No CSVs in $(RAW_DIR). Drop the nine challenge files there, or pass RAW_DIR=path/to/csvs"; exit 1; }
	XRAY_DATA_DIR=$(RAW_DIR) uv run python -m xray.pipeline.clean
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
	XRAY_DATA_DIR=$(RAW_DIR) uv run python -m xray.pipeline

# Everything, one command. Data first (clean, cash, panel, score, monitor, serving tables, the
# JSON copy the web falls back to), then the API and the web side by side; Ctrl-C stops both.
# A server already answering on its port is reused, not fought over: an API started with
# `make api` in another terminal re-reads the freshly published tables on its own.
lighthouse: install $(WEB_DEPS) serve web-data ## From the raw CSVs to a running demo: load, score, publish, then API on :8000 and web on :5173 (API_PORT, WEB_PORT to change). make lighthouse [RAW_DIR=path/to/csvs]
	@api=$$(curl -s -o /dev/null -w '%{http_code}' http://localhost:$(API_PORT)/health || true); \
	web=$$(curl -s -o /dev/null -w '%{http_code}' http://localhost:$(WEB_PORT)/ || true); \
	if [ "$$api" != "200" ] && lsof -ti tcp:$(API_PORT) >/dev/null 2>&1; then \
		echo "Port $(API_PORT) is taken by something that is not the API:"; lsof -i tcp:$(API_PORT) -P -n | tail -n +2; \
		echo "Stop it, or run: make lighthouse API_PORT=8001"; exit 1; fi; \
	if [ "$$web" != "200" ] && lsof -ti tcp:$(WEB_PORT) >/dev/null 2>&1; then \
		echo "Port $(WEB_PORT) is taken by something that is not the web:"; lsof -i tcp:$(WEB_PORT) -P -n | tail -n +2; \
		echo "Stop it, or run: make lighthouse WEB_PORT=5174"; exit 1; fi; \
	echo; echo "  Lighthouse is coming up."; \
	echo "  web  http://localhost:$(WEB_PORT)        api  http://localhost:$(API_PORT)/docs"; \
	[ "$$api" = "200" ] && echo "  API already running on :$(API_PORT), reusing it (it re-reads the tables just published)."; \
	[ "$$web" = "200" ] && echo "  Web already running on :$(WEB_PORT), reusing it."; \
	echo "  In another terminal: make replay FROM=2025-01 PAUSE=8 to watch the real months land,"; \
	echo "  or make demo FROM=2025-01 PAUSE=8 for the named synthetic portfolio. Ctrl-C stops what this started."; \
	echo "  make lighthouse-down stops both wherever they were started."; echo; \
	start=""; [ "$$api" = "200" ] || start="$$start api"; [ "$$web" = "200" ] || start="$$start web"; \
	if [ -n "$$start" ]; then $(MAKE) -j2 $$start; else echo "  Both already up, nothing to start."; fi

lighthouse-down: ## Stop whatever listens on the API and web ports
	@for port in $(API_PORT) $(WEB_PORT); do \
		pids=$$(lsof -ti tcp:$$port 2>/dev/null); \
		if [ -n "$$pids" ]; then echo "stopping :$$port (pid $$pids)"; kill $$pids 2>/dev/null || true; else echo ":$$port free"; fi; \
	done

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

notify: $(ALERTS) ## Send the pending alerts: make notify [MONTH=2026-05] [CHANNEL=slack|email|rules]
	uv run python -m xray.scoring.notify --channel $(or $(CHANNEL),slack) $(if $(MONTH),--month $(MONTH))

serve: $(PANEL) ## Write the real serving tables (scores, drivers, alerts, offers, actions, payers, promptpay) to data/serving
	uv run python -m xray.scoring.serve
	uv run python -m xray.scoring.payers
	uv run python -m xray.scoring.promptpay

submit: ## Score a hidden-test dump end to end: make submit RAW=path/to/csvs [OUT=submission]
	uv run python -m xray.scoring.submit --raw-dir $(RAW) --out $(or $(OUT),submission)

replay: ## Land the dump month by month, publish and alert after each: make replay [FROM=2025-01] [TO=2026-08] [PAUSE=8] [CHANNEL=slack|email|rules|none] [RESET=1] [CHECK=1]
	uv run python -m xray.pipeline.replay --raw-dir $(RAW_DIR) \
		$(if $(FROM),--from $(FROM)) $(if $(TO),--to $(TO)) $(if $(PAUSE),--pause $(PAUSE)) \
		$(if $(CHANNEL),--channel $(CHANNEL)) $(if $(RESET),--reset) $(if $(CHECK),--check)

DEMO_DIR := data/demo

demo-data: ## Generate the synthetic Spanish scale-up dump (nine CSVs, invented figures) in data/demo/raw
	uv run python -m xray.pipeline.synth --out $(DEMO_DIR)/raw

# Companies connecting to the platform: the portfolio make lighthouse built stays as it is, the
# named groups arrive on top of it in batches, each scored on the spot with its whole history.
demo: demo-data ## Live demo: the named groups connect in BATCHES (2) arrivals GAP (20) s apart, on top of the current portfolio. make lighthouse first; make serve restores the tables after
	uv run python -m xray.pipeline.onboard --new $(DEMO_DIR)/raw \
		--batches $(or $(BATCHES),2) --gap $(or $(GAP),20) $(if $(CHANNEL),--channel $(CHANNEL))

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
api: ## Run the API locally with reload on http://localhost:8000 (API_PORT to change)
	uv run uvicorn xray.api.main:app --reload --port $(API_PORT)

api-up: ## Start the API container in the background
	docker compose up -d --build

api-down: ## Stop the API container
	docker compose down

slack-test: ## Send a test alert to the Slack webhook in .env
	uv run python -m xray.integrations.slack

email-test: ## Send a test alert to the SMTP host in .env
	uv run python -m xray.integrations.email

# Web demo
$(WEB_DEPS): web/package.json web/package-lock.json
	cd web && npm install --no-audit --no-fund

web-install: $(WEB_DEPS) ## Install the demo front end dependencies

macro: ## Refresh web/src/lib/macro.json from the ECB, Eurostat, the ONS and Yahoo Finance
	uv run python -m xray.pipeline.fetch_macro

web-data: ## Export data/serving parquet to web/public/data as JSON for the front end
	uv run python -m xray.pipeline.export_serving

web: web-data ## Run the demo front end on http://localhost:5173, talking to the API on :8000 (WEB_PORT, API_PORT to change)
	cd web && VITE_API_URL=http://localhost:$(API_PORT) npm run dev -- --port $(WEB_PORT) --strictPort

web-build: $(WEB_DEPS) web-data ## Build the demo front end into web/dist
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

# Infrastructure

How data gets from nine CSVs to a container that answers the demo, and what runs where. The pipeline side (clean, panel, lake, why parquet and not a `.duckdb` file) is in [`architecture.md`](architecture.md); this file covers the serving side, configuration and CI.

**One idea holds it together:** heavy work happens offline, on a laptop, once. The online side only reads a small finished file. The 650 MB of raw data never leaves the machine; what gets served is a few MB of scores, drivers and alerts. That is why everything fits in free tiers and the demo cannot be slow.

## The flow

```mermaid
flowchart LR
    subgraph OFF["OFFLINE · laptop · uv · make targets"]
        direction LR
        RAW[("data/raw<br/>9 CSVs · 650 MB")]
        CLEAN["clean<br/><code>make clean-data</code>"]
        PROC[("data/processed<br/>parquet")]
        FEAT["panel<br/>monthly, per group,<br/>no look-ahead"]
        SCORE["score + drivers<br/>+ states"]
        RAW --> CLEAN --> PROC --> FEAT --> SCORE
    end

    SERV[("data/serving/<br/><b>*.parquet</b><br/>a few MB")]
    SCORE ==>|writes| SERV

    subgraph ON["ONLINE · Docker · 349 MB image"]
        direction LR
        API["FastAPI<br/>in-memory DuckDB,<br/>one view per parquet"]
    end

    SERV ==>|"mounted (local)<br/>baked in (deploy)"| API
    API -->|JSON /api/v1| FRONT["demo front end<br/><code>web/</code>"]
    SCORE -.->|"state change:<br/>Bending, Falling, Improving"| SLACK["Slack webhook<br/><code>xray.integrations.slack</code>"]
    SCORE -.-> SUB["hidden-test<br/>predictions"]

    classDef store fill:#1f2937,stroke:#60a5fa,color:#f9fafb
    classDef built fill:#064e3b,stroke:#34d399,color:#f9fafb
    classDef todo fill:#3f3f46,stroke:#a1a1aa,color:#e4e4e7,stroke-dasharray:4 3
    class RAW,PROC,SERV store
    class CLEAN,FEAT,SCORE,SUB,API,SLACK built
    class FRONT todo
```

Green is built, dashed grey is still to come, blue is data at rest.

The contract between the two halves is **one folder**: `data/serving/*.parquet`. The pipeline owns writing it, the API only reads it, and each file becomes a table named after it. There is deliberately no `.duckdb` file: a DuckDB file held open by a writer locks out every reader, parquet does not (see `architecture.md` section 4). Whoever builds the score and whoever builds routes can work in parallel as long as they agree on those tables.

## What runs where

| Piece | Runs on | Started with | Needs |
|---|---|---|---|
| Pipeline (clean, panel, then score) | laptop with `uv`, or Docker | `make panel`, `make pipeline`, `make docker-pipeline` | `pipeline` dependency group (pandas, pyarrow, scikit-learn) |
| Score, alerts, serving tables | laptop with `uv`, or Docker | `make score`, `make monitor`, `make serve` | same |
| Hidden-test submission | laptop with `uv`, or Docker | `make submit RAW=path/to/csvs` | same |
| API, dev mode | laptop, `uv` | `make api` (auto-reload, docs at `/docs`) | core dependencies only |
| API, container | Docker, target `api` | `make api-up` / `make api-down` | Docker |
| Alerts | wherever the pipeline runs | `make slack-test` to try it | `XRAY_SLACK_WEBHOOK_URL` |
| CI | GitHub Actions | every push to `main` | nothing, no secrets |

## Local versus deployed

Same image in both cases. Only the origin of the parquet files changes.

```mermaid
flowchart TB
    subgraph L["Local: docker compose"]
        H["host: data/serving/*.parquet"] -->|"volume, read-only"| C1["container /app/data/serving"]
    end
    subgraph D["Deployed: Render, Cloud Run..."]
        B["docker build<br/>COPY data/serving"] --> C2["files live inside the image"]
    end
```

- **Local**: compose mounts the host folder over the image's copy. Re-run the pipeline, restart the container, new scores. No rebuild.
- **Deploy**: run the pipeline, then build. The image carries its data, so the host needs no database, no volume and no secret to serve the demo. Redeploy to refresh scores.

The API also starts with no tables at all (`/health` then reports `"tables": []`), so the container is never blocked on the pipeline.

## Configuration

Everything is read by `src/xray/settings.py` with the `XRAY_` prefix. Precedence: real environment variable, then `.env`, then the default. Copy `.env.example` to `.env`; every variable is optional.

| Variable | Default | Purpose |
|---|---|---|
| `XRAY_ENV` | `local` | Shown by `/health`. The image sets `docker`. |
| `XRAY_LOG_LEVEL` | `INFO` | |
| `XRAY_PORT` | `8000` | Host port used by compose. |
| `XRAY_DATA_DIR` | `data/raw` | Raw CSV folder, pipeline only. |
| `XRAY_SERVING_DIR` | `data/serving` | The image pins it to `/app/data/serving`. |
| `XRAY_PROCESSED_DIR`, `XRAY_LAKE_DIR` | `data/processed`, `data/lake` | Pipeline only. |
| `XRAY_CORS_ORIGINS` | localhost 3000 and 5173 | JSON list. Add the front end URL once it exists. |
| `XRAY_SLACK_WEBHOOK_URL` | empty | Without it `send_slack` logs the alert and returns `False`. |

`.env` is git-ignored. `.env.example` is the only env file in git, and it holds no secrets.

## The images

One `Dockerfile`, two targets. `pipeline` is built with `make docker-build` (`--target pipeline`, documented in `architecture.md` section 10). `api` is the last stage, so it is what a plain `docker build .` produces: Render cannot pick a target and builds the last one. Compose builds it too, in two stages from the lockfile:

1. **builder**: installs dependencies (cached layer, rebuilt only when `uv.lock` changes), then the package.
2. **runtime**: `python:3.12-slim`, the virtualenv copied over, a non-root user, a `HEALTHCHECK` on `/health`, and `uvicorn` listening on `$PORT` (hosts inject it) or 8000.

The pipeline libraries live in the `pipeline` dependency group. Laptops install it by default (`[tool.uv] default-groups`), the image installs with `--no-default-groups`. Result: 349 MB instead of 1.02 GB. **An import of pandas inside `xray.api` will work on a laptop and crash in the container**: query DuckDB directly there.

`.dockerignore` excludes `data` except `data/serving`, so raw data cannot end up in an image by accident.

## CI

```mermaid
flowchart LR
    P["push to main"] --> A["checks<br/>uv sync --frozen<br/>make ci: ruff + pytest"]
    P --> B["docker<br/>build the image, no push<br/>layer cache in GHA"]
    A --> OK(["green badge"])
    B --> OK
```

Both jobs run in parallel and use no secrets. There is no CD job: the API has `autoDeployTrigger: checksPass` in `render.yaml`, so Render deploys a push to `main` once these checks are green. The static site deploys on every push.

## Deploy: Render, free, no card

`render.yaml` at the repo root is a Blueprint with two services. In Render: New > Blueprint, pick the repo, apply.

| Service | What | Sleeps |
|---|---|---|
| `xray` | static site, `web/` built with `npm ci && npm run build`, served from a CDN | never |
| `xray-api` | the `api` image, Frankfurt, health check on `/health` | after 15 min idle, about a minute to wake |

- The demo only needs the static site, which reads `web/public/data/*.json`. Those files are in git: after the serving tables or the agent cache change, run `make publish` (re-exports the JSON and stages what Render serves), then commit and push.
- `data/serving/context/*.json` (agent context cache) is in git for the same reason: a git build has no other way to get it.
- Only the Agents chat needs secrets: set `HELMCODE_API_KEY`, `EXA_API_KEY` and `TAVILY_API_KEY` on
  `xray-api` in the Render dashboard (`sync: false` in `render.yaml`). The static site gets the
  API address at build time through `VITE_API_URL`; locally it defaults to `http://localhost:8000`.
- Nothing else on the API needs secrets. If Render gives the site another hostname, update `XRAY_CORS_ORIGINS` in `render.yaml`.
- Before the pitch, open `/health` on the API to wake it, or point a free UptimeRobot monitor at it every 5 minutes.
- Fallback on stage: `make api-up` plus `cloudflared tunnel --url http://localhost:8000`.

## Serving schema

`docs/serving-contract.md`. Written by `make serve` from the real score; `make web-data` re-exports it as JSON for the static front end.


# Local V3 scorecard serving

`uv run python -m xray.scoring.local_serving --output-dir data/processed/v3-serving`
exports the company and group observations produced by the local V2 scorecard.
It does not modify V2 HTML, its manifest, or processed source tables.
The V2 HTML cache is reused only when its output hash and complete input hash map
match the current files. Otherwise the existing V2 builder and FX normalization run
in memory against the current processed tables. The current pipeline cleaner is not run.

Set `XRAY_SERVING_DIR=data/processed/v3-serving` before starting the API.
From the repository root in PowerShell, start the API with the viewer's allowed origins:

```powershell
$env:XRAY_SERVING_DIR = 'data/processed/v3-serving'
$env:XRAY_CORS_ORIGINS = '["http://127.0.0.1:8765","http://localhost:8765"]'
uv run --frozen --no-sync uvicorn xray.api.main:app --host 127.0.0.1 --port 8000
```

In a separate terminal, also from the repository root, serve the generated viewer:

```powershell
uv run --frozen --no-sync python -m http.server 8765 --bind 127.0.0.1 --directory data/processed
```

Open `http://127.0.0.1:8765/xray-v3.html` after building the V3 frontend.

This directory contains `score_entities.parquet`, `score_observations.parquet`, and
`score_profile.json` with the frozen config, source hashes, exporter hash and original
V2 manifest. Legacy score marts are not loaded when local score entities are present.
No offers or alert tables are copied into this profile.

The browser reads `/api/v1/scoring/portfolio?kind=group|company` for metadata and
monthly score summaries, then `/api/v1/scoring/entities/{id}` for the selected
entity's complete monthly evidence. Portfolio records preserve missing scores.
`POST /api/v1/scoring/entities/{id}/evaluate` accepts partial `weights` overrides
for `level`, `financial`, and `evolution`. Each family requires finite, nonnegative
known weights and a positive total. Evaluation recalculates the monthly series
without modifying the exported catalog. Missing observations stay null.
Evaluation returns members as navigation metadata without level or confidence,
because only the selected entity's monthly series is recalculated.

Python consumers use `read_entity(db, entity_id, cutoff, config)` and
`reweight_entity(detail, weights)` from `xray.scoring.local_serving`.
Cutoffs are inclusive ISO months. Reads use SQL parameters; dated debt snapshots
later than the cutoff are excluded. Runtime scoring does not import pandas.
Confidence measures available evidence; it is not a probability of accuracy.

## Browser build

From `web/`, run `npm ci --no-audit --no-fund`, then `npm run build:v3`.
The script defaults to API `http://127.0.0.1:8000`; set `VITE_API_URL` before
building to use another API origin. It checks TypeScript, builds both Vite entries
under `data/processed/v3-web/`, and publishes `data/processed/xray-v3.html`
with relative references to `v3-web/assets/`. It does not change `xray-v2.html`.

Serve `data/processed/` with
`uv run python -m http.server 8765 --bind 127.0.0.1 --directory data/processed`
from the repository root, then open `http://127.0.0.1:8765/xray-v3.html`.
The scoring API must be running with the V3 serving directory above. This entry
never falls back to the baseline JSON export. `web/index.html` keeps the main demo.

V3 mounts the shared `App.tsx` and components, preserving the
Embat/Lighthouse brand, Groups/Alerts/Agents tabs, filters, favorites, chart zoom
and market overlays. A scope selector switches between groups and companies.
The default `web/index.html` entry retains baseline data loading.

Temporary weights belong to each entity for the browser session. Applying weights
replaces that entity's series in the shared store used by the detail and sidebar.
Other entities retain their own profiles. Switching scope
or syncing preserves custom profiles; opening a member preserves the selected month.
The Agents tab sends the same entity, month, and applied weights as the detail.
Local conversations use separate storage, and history sent to the agent is limited
to the current entity, month, and weights.

Health level and evolution are separate scores; evolution has a neutral value of 50.
Numeric score bands are display groups, not validated health classifications.
Confidence describes evidence completeness. Missing observations remain gaps.
The local profile has no monitor alerts, offers, prompt-payment forecasts, or
baseline monthly trend model. Their baseline outputs are not substituted into V3.
Member rows provide navigation metadata without inventing current member scores.
The currency toggle uses the main frontend's bundled annual EUR/USD reference rates.

## Natural-language view assistant

The floating `✨` button opens an assistant for the selected entity and month.
`POST /api/v1/view-chats` reads local evidence with prepared, parameterized queries.
The existing Helmcode provider is configured by `HELMCODE_API_KEY` in `.env`.
The response carries validated weight and chart actions; no database writes or generated code run.
Weight actions blend the four existing pillar scores only, with session-local reset controls.
The manual weight editor remains a separate endpoint that evaluates the local scorecard.
Charts support line, area and bar types, selected pillar series, color, grid, title and month window.
Each requested series needs two finite observations within the selected period; unsupported series are omitted with a reason.
If every requested series is unavailable, the current chart settings remain in place.
The prompt forbids invented facts, numbers and dates, and distinguishes observed evidence from interpretations of relationships.
Missing data stays missing, and a snapshot cannot be projected backwards as history.
Provider errors or invalid actions leave the view unchanged and return an explanation.

The local scoring and view assistant routes use the same API-key protection as the rest of `/api/v1`.
When `LIGHTHOUSE_API_KEY` is set on the API, build the frontend with the matching `VITE_API_KEY`.

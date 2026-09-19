# Two images from one file. `pipeline`: raw CSVs in, parquet out (`make docker-build`).
# `api` is the demo backend: no pandas, the serving parquet baked in. It is the last stage
# because hosts that cannot pick a target (Render) build the last one.

FROM python:3.12-slim AS pipeline

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Dependencies resolve in their own layer: they change far less often than the source does.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --no-dev

# Raw data is mounted, never baked in: the CSVs are 615 MB and stay out of the image.
ENV XRAY_DATA_DIR=/data/raw \
    XRAY_PROCESSED_DIR=/data/processed \
    XRAY_MARTS_DIR=/data/marts \
    XRAY_LAKE_DIR=/data/lake

CMD ["python", "-m", "xray.pipeline"]


FROM python:3.12-slim AS api-builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_CACHE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups --no-install-project
COPY src/ ./src/
RUN uv sync --frozen --no-default-groups --no-editable


FROM python:3.12-slim AS api
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=api-builder /app/.venv /app/.venv
# Pipeline output. Locally docker compose mounts the live folder over it. Owned by the app
# user because the chat writes the alert rule book next to the tables.
COPY --chown=app:app data/serving /app/data/serving
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    XRAY_ENV=docker \
    XRAY_SERVING_DIR=/app/data/serving
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
# PORT is injected by most hosts (Render, Cloud Run).
CMD ["sh", "-c", "uvicorn xray.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

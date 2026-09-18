# Pipeline image: raw CSVs in, parquet panel out. Built and run through the docker-* Make targets.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
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
    XRAY_LAKE_DIR=/data/lake

CMD ["python", "-m", "xray.pipeline"]

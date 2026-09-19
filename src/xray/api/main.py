"""FastAPI application for the demo backend."""

import logging
from contextlib import asynccontextmanager

import duckdb
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from xray.api.routers import alerts, health
from xray.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    # In-memory DuckDB with one view per parquet file: no database file, so no lock to fight over.
    # The API starts with zero tables so the container can run before the pipeline has.
    app.state.db = duckdb.connect()
    app.state.tables = []
    for path in sorted(settings.serving_dir.glob("*.parquet")):
        app.state.db.sql(f"create view {path.stem} as select * from '{path}'")
        app.state.tables.append(path.stem)
    if not app.state.tables:
        logger.warning("No parquet tables found in %s", settings.serving_dir)
    yield
    app.state.db.close()


app = FastAPI(title="X Ray", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


app.include_router(health.router)
app.include_router(alerts.router)

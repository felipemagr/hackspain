"""FastAPI application for the demo backend."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from xray.api.routers import alerts, chat, health, real_groups
from xray.config import MARTS_DIR
from xray.settings import get_settings

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


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
    app.state.real_tables = set(app.state.tables) & {"real_scores", "real_drivers"}
    for name in ("real_scores", "real_drivers"):
        path = MARTS_DIR / f"{name}.parquet"
        if path.is_file():
            escaped = str(path).replace("'", "''")
            app.state.db.sql(f"create or replace view {name} as select * from '{escaped}'")
            app.state.real_tables.add(name)
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
app.include_router(real_groups.router)
app.include_router(alerts.router)
app.include_router(chat.router)
app.mount("/viewer/assets", StaticFiles(directory=STATIC_DIR), name="viewer-assets")


@app.get("/viewer", include_in_schema=False)
def viewer() -> FileResponse:
    """Open the internal viewer for calculated group scores."""
    return FileResponse(STATIC_DIR / "viewer.html")

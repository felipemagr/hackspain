"""FastAPI application for the demo backend."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb
from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from xray.api.auth import require_api_key
from xray.api.db import refresh_views
from xray.api.routers import (
    alert_rules,
    alerts,
    chat,
    client_errors,
    health,
    real_groups,
    tables,
    version,
)
from xray.config import MARTS_DIR, PROCESSED_DATA_DIR
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
    refresh_views(app)
    app.state.real_tables = set(app.state.tables) & {"real_scores", "real_drivers"}
    for name in ("real_scores", "real_drivers"):
        path = MARTS_DIR / f"{name}.parquet"
        if path.is_file():
            escaped = str(path).replace("'", "''")
            app.state.db.sql(f"create or replace view {name} as select * from '{escaped}'")
            app.state.real_tables.add(name)
    if not app.state.tables:
        logger.warning("No parquet tables found in %s", settings.serving_dir)
    # The raw trail, where it exists (it is not in the API image): the chat queries it.
    for path in sorted(PROCESSED_DATA_DIR.glob("*.parquet")):
        name = f"raw_{path.stem}" if path.stem in app.state.tables else path.stem
        escaped = str(path).replace("'", "''")
        app.state.db.sql(f"create or replace view {name} as select * from '{escaped}'")
    # The chat runs SQL a model wrote: nothing outside the data directories can be read.
    allowed = [
        str(d).replace("'", "''") for d in (settings.serving_dir, MARTS_DIR, PROCESSED_DATA_DIR)
    ]
    app.state.db.sql(f"set allowed_directories = {allowed}")
    app.state.db.sql("set enable_external_access = false")
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


# Open: the health check Render polls, and the mart behind the internal viewer, which is a plain
# page with no key to send.
app.include_router(health.router)
app.include_router(real_groups.router)
for protected in (version, tables, alerts, alert_rules, chat, client_errors):
    app.include_router(protected.router, dependencies=[Depends(require_api_key)])
app.mount("/viewer/assets", StaticFiles(directory=STATIC_DIR), name="viewer-assets")


@app.get("/viewer", include_in_schema=False)
def viewer() -> FileResponse:
    """Open the internal viewer for calculated group scores."""
    return FileResponse(STATIC_DIR / "viewer.html")

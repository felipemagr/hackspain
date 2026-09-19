"""Which build of the serving tables is live. The front end polls this to know when to refetch."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from xray.api.db import refresh_views
from xray.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["ops"])

VERSION_FILE = "_version.json"


class Version(BaseModel):
    """Identity of the published tables. ``build_id`` changes on every publish."""

    build_id: str
    built_at: str
    as_of: str | None = None
    latest_month: str | None = None
    n_groups: int | None = None
    n_alerts: int | None = None
    tables: list[str]


@router.get("/version", response_model=Version)
async def version(request: Request) -> Version:
    """The live build. Also re-registers the views when a table file appeared or vanished."""
    tables = refresh_views(request.app)
    path = get_settings().serving_dir / VERSION_FILE
    if path.exists():
        return Version(**{**json.loads(path.read_text()), "tables": tables})
    # Tables published before the version stamp existed: derive an id from the newest file.
    stamps = [(get_settings().serving_dir / f"{t}.parquet").stat().st_mtime for t in tables]
    newest = datetime.fromtimestamp(max(stamps, default=0), UTC)
    return Version(
        build_id=newest.strftime("%Y%m%dT%H%M%S.%f"),
        built_at=newest.isoformat(timespec="seconds"),
        tables=tables,
    )

"""Whole serving tables as JSON, the same shape as the static export the front end started on."""

import gzip
import json
import math

from fastapi import APIRouter, HTTPException, Request, Response, status

from xray.settings import get_settings

router = APIRouter(prefix="/api/v1/tables", tags=["tables"])

# name -> (etag, gzipped JSON). A publish rewrites the parquet, which changes the etag.
_bodies: dict[str, tuple[str, bytes]] = {}


def _clean(value):
    # JSON has no NaN; the front end expects null where the parquet has none.
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _body(name: str, request: Request) -> tuple[str, bytes]:
    stat = (get_settings().serving_dir / f"{name}.parquet").stat()
    etag = f'"{name}-{stat.st_mtime_ns}-{stat.st_size}"'
    cached = _bodies.get(name)
    if cached and cached[0] == etag:
        return cached
    # Sync handlers run on worker threads, and a DuckDB connection is not shared across them.
    cursor = request.app.state.db.cursor().execute(f"select * from {name}")
    columns = [c[0] for c in cursor.description]
    rows = [dict(zip(columns, map(_clean, row), strict=True)) for row in cursor.fetchall()]
    payload = json.dumps(rows, default=lambda v: v.isoformat(), separators=(",", ":"))
    _bodies[name] = (etag, gzip.compress(payload.encode(), compresslevel=5))
    return _bodies[name]


@router.get("/{name}", response_model=list[dict])
def read_table(name: str, request: Request) -> Response:
    """Every row of one serving table (``scores``, ``drivers``, ``alerts``...)."""
    if name not in request.app.state.tables:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")
    etag, body = _body(name, request)
    # no-cache: the browser keeps the copy but asks first, and a 304 costs no body.
    headers = {"ETag": etag, "Cache-Control": "private, no-cache", "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    if "gzip" not in request.headers.get("accept-encoding", ""):
        return Response(gzip.decompress(body), media_type="application/json", headers=headers)
    headers["Content-Encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)

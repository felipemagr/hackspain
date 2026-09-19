"""Whole serving tables as JSON, the same shape as the static export the front end started on."""

import math

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(prefix="/api/v1/tables", tags=["tables"])


def _clean(value):
    # JSON has no NaN; the front end expects null where the parquet has none.
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


@router.get("/{name}", response_model=list[dict])
async def read_table(name: str, request: Request) -> list[dict]:
    """Every row of one serving table (``scores``, ``drivers``, ``alerts``...)."""
    if name not in request.app.state.tables:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")
    cursor = request.app.state.db.execute(f"select * from {name}")
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, map(_clean, row), strict=True)) for row in cursor.fetchall()]

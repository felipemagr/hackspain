"""The monitor's feed: what moved, when, and why."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["alerts"])

COLUMNS = """group_id, month, kind, direction, state_from, state_to, onset_month,
    level_at_onset, level_at_alert, delta_level, trend, compound, tier, driver_1, driver_2,
    sigmas, resolution, severity, anticipation_months, late"""


class Alert(BaseModel):
    """One moment a group moved enough to be worth a message."""

    group_id: str
    month: date
    kind: str
    direction: str
    state_from: str
    state_to: str
    onset_month: date
    level_at_onset: float
    level_at_alert: float
    delta_level: float
    trend: float
    compound: float
    tier: str
    driver_1: str | None = None
    driver_2: str | None = None
    sigmas: float | None = None
    resolution: str | None = None
    severity: float
    anticipation_months: float | None = None
    late: bool


class AlertPage(BaseModel):
    """A page of alerts, worst first."""

    data: list[Alert]
    total: int
    offset: int
    limit: int


def _query(request: Request, where: str, params: list) -> list[dict]:
    if "alerts" not in request.app.state.tables:
        return []
    sql = f"select {COLUMNS} from alerts {where}"
    return request.app.state.db.execute(sql, params).df().to_dict("records")


@router.get("/alerts", response_model=AlertPage)
async def list_alerts(
    request: Request,
    since: Annotated[date | None, Query(description="first month, inclusive")] = None,
    until: Annotated[date | None, Query(description="last month, inclusive")] = None,
    kind: Annotated[str | None, Query(description="jump or shift")] = None,
    direction: Annotated[str | None, Query(description="down or up")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AlertPage:
    """List alerts across the portfolio, most recent and most severe first."""
    filters, params = [], []
    for column, value in (("kind", kind), ("direction", direction)):
        if value:
            filters.append(f"{column} = ?")
            params.append(value)
    if since:
        filters.append("month >= ?")
        params.append(since)
    if until:
        filters.append("month <= ?")
        params.append(until)
    where = ("where " + " and ".join(filters)) if filters else ""

    rows = _query(request, where + " order by month desc, severity desc", params)
    return AlertPage(
        data=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit
    )


@router.get("/groups/{group_id}/alerts", response_model=list[Alert])
async def group_alerts(request: Request, group_id: str) -> list[Alert]:
    """Every alert raised on one group, oldest first. Empty when it never moved."""
    return _query(request, "where group_id = ? order by month", [group_id])

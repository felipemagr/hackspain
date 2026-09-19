"""Read-only access to the calculated group score mart."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/real-groups", tags=["real-groups"])


class GroupSummary(BaseModel):
    """Latest calculated month for one group."""

    group_id: str
    month: datetime
    level: float | None
    trend: float | None
    state: str
    coverage: float
    uncategorized_share: float | None
    currency_mixed: bool


class GroupList(BaseModel):
    """Paginated group summary with mart availability."""

    data: list[GroupSummary]
    total: int
    offset: int
    limit: int
    available: bool


class ScoreMonth(BaseModel):
    """One calculated group month, including input quality indicators."""

    group_id: str
    month: datetime
    liquidity: float | None
    cash_generation: float | None
    payment_discipline: float | None
    collections: float | None
    debt_burden: float | None
    level: float | None
    level_uncapped: float | None
    is_capped: bool
    coverage: float
    uncategorized_share: float | None
    currency_mixed: bool
    trend: float | None
    compound: float | None
    state: str
    tier: str | None
    months_observed: float
    buffer_days: float | None
    operating_margin: float | None
    ap_days_beyond_terms: float | None
    ar_days_beyond_terms: float | None
    known_inflow_3m: float | None


class PillarDriver(BaseModel):
    """A pillar contribution and its change from the prior month."""

    group_id: str
    month: datetime
    pillar: str
    score: float | None
    contribution: float
    delta_score: float | None
    delta_contribution: float | None


class GroupDetail(BaseModel):
    """Complete observed trajectory and named drivers for one group."""

    group_id: str
    scores: list[ScoreMonth]
    drivers: list[PillarDriver]


def _rows(db, query: str, params: list | None = None) -> list[dict]:
    cursor = db.execute(query, params or [])
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


@router.get("", response_model=GroupList)
def list_groups(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=250, ge=1, le=500),
) -> GroupList:
    """List the latest real score for each group, including missing scores."""
    if "real_scores" not in request.app.state.real_tables:
        return GroupList(data=[], total=0, offset=offset, limit=limit, available=False)

    db = request.app.state.db
    total = db.execute("select count(distinct group_id) from real_scores").fetchone()[0]
    data = _rows(
        db,
        """
        select group_id, month, level, trend, state, coverage,
               uncategorized_share, currency_mixed
        from (
            select *, row_number() over (partition by group_id order by month desc) as rn
            from real_scores
        ) where rn = 1
        order by group_id
        limit ? offset ?
        """,
        [limit, offset],
    )
    return GroupList(data=data, total=total, offset=offset, limit=limit, available=True)


@router.get("/{group_id}", response_model=GroupDetail)
def get_group(request: Request, group_id: str) -> GroupDetail:
    """Get monthly scores and pillar drivers for one real group."""
    if "real_scores" not in request.app.state.real_tables:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Baseline scores are not available. Run make score-baseline first.",
        )
    scores = _rows(
        request.app.state.db,
        "select * from real_scores where group_id = ? order by month",
        [group_id],
    )
    if not scores:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    drivers = []
    if "real_drivers" in request.app.state.real_tables:
        drivers = _rows(
            request.app.state.db,
            "select * from real_drivers where group_id = ? order by month, pillar",
            [group_id],
        )
    return GroupDetail(group_id=group_id, scores=scores, drivers=drivers)

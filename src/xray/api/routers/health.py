"""Liveness probe used by Docker and the hosting platform."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from xray.settings import get_settings

router = APIRouter(tags=["ops"])


class HealthResponse(BaseModel):
    """Liveness and which serving tables are loaded."""

    status: str
    env: str
    tables: list[str]


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Liveness probe used by Docker and the hosting platform."""
    return HealthResponse(
        status="ok",
        env=get_settings().env,
        tables=request.app.state.tables,
    )

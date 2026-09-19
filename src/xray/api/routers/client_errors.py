"""Errors the page hits in someone's browser, written to the API log.

The front end is a static site: without this a broken screen leaves no trace anywhere. With it,
Render's log for the API shows the message, the component stack and the URL it happened on.
"""

import logging

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, field_validator

logger = logging.getLogger("xray.client")
router = APIRouter(prefix="/api/v1", tags=["ops"])

MAX_FIELD_CHARS = 4000


class ClientError(BaseModel):
    """One error as the browser saw it. Every field is free text and gets truncated."""

    message: str
    source: str = "render"
    url: str | None = None
    stack: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _truncate(cls, value: object) -> object:
        return value[:MAX_FIELD_CHARS] if isinstance(value, str) else value


@router.post("/client-errors", status_code=status.HTTP_204_NO_CONTENT)
async def report_client_error(body: ClientError, request: Request) -> None:
    """Log a front end error so it shows up next to the API's own logs."""
    logger.error(
        "client %s error on %s: %s | agent=%s\n%s",
        body.source,
        body.url,
        body.message,
        request.headers.get("user-agent", "")[:120],
        body.stack or "",
    )

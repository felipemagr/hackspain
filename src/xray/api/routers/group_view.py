"""Session-scoped group score preferences and their derived tables."""

import logging

from fastapi import APIRouter, HTTPException, Request, status

from xray.agents.group_view import GroupViewRequest, run_group_view
from xray.scoring.session import GroupWeights, evaluate_group
from xray.settings import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["view assistant"])


@router.post("/groups/{group_id}/evaluations")
def evaluate(group_id: str, body: GroupWeights, request: Request) -> dict:
    """Recalculate the group's historical view without changing published data."""
    try:
        tables = evaluate_group(request.app.state.db, group_id, body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    if tables is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no data for this group.")
    return {"weights": body.model_dump(), "tables": tables}


@router.post("/group-view-chats")
def chat(body: GroupViewRequest, request: Request) -> dict:
    """Analyze the selected group or company and apply explicit group score preferences."""
    try:
        return run_group_view(body, request.app.state.db, get_settings())
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except Exception as exc:  # Provider failure must preserve the currently displayed weights.
        logger.warning("Group view assistant failed", exc_info=True)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not read the card. The view has not changed. Please retry.",
        ) from exc

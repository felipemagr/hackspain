"""Natural-language changes to temporary browser weights and chart settings."""

from fastapi import APIRouter, HTTPException, Request, status

from xray.agents.view import ViewChatRequest, ViewChatResponse, run_view_chat
from xray.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["view assistant"])


@router.post("/view-chats", response_model=ViewChatResponse)
def create_view_chat(body: ViewChatRequest, request: Request) -> ViewChatResponse:
    """Read selected financial evidence and return validated, reversible view actions."""
    tables = getattr(request.app.state, "tables", ())
    profile = getattr(request.app.state, "score_profile", None)
    if not {"score_entities", "score_observations"}.issubset(tables) or not profile:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "El asistente necesita los datos locales de scoring para consultar esta vista.",
        )
    result = run_view_chat(body, request.app.state.db, get_settings(), profile["config"])
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No hay datos para esta entidad y fecha.")
    return result

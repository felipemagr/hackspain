"""The agent chat. The one route that reaches the model and the web during a request:
everything else the demo shows is precomputed, so the demo stands when this does not."""

import json
from collections.abc import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from xray.agents.fleet import ROSTER, ChatRequest, FleetMember, run_chat
from xray.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["chat"])


class FleetResponse(BaseModel):
    """The agents the chat can dispatch, and whether the model behind them is configured."""

    agents: list[FleetMember]
    model: str | None


@router.get("/agents", response_model=FleetResponse)
async def list_agents() -> FleetResponse:
    """List the fleet."""
    settings = get_settings()
    return FleetResponse(
        agents=list(ROSTER), model=settings.llm_model if settings.helmcode_api_key else None
    )


@router.post("/chats")
def create_chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """Answer one question as a stream of server-sent events: plan, agents, tokens, done."""

    def events() -> Iterator[str]:
        for event in run_chat(body, request.app.state.db, get_settings()):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

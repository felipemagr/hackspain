"""The agent chat. The one route that reaches the model and the web during a request:
everything else the demo shows is precomputed, so the demo stands when this does not."""

import json
from collections.abc import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from xray.agents.fleet import ROSTER, FleetMember, run_chat
from xray.agents.fleet import ChatRequest as FleetChatRequest
from xray.agents.local_scoring import run_local_chat
from xray.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(FleetChatRequest):
    """Accept a company or group and optional local score weight overrides."""

    group_id: str = ""
    month: str = ""
    entity_id: str | None = None
    weights: dict[str, dict[str, float]] | None = None


class FleetResponse(BaseModel):
    """The agents the chat can dispatch, and whether the model behind them is configured."""

    agents: list[FleetMember]
    model: str | None


@router.get("/agents", response_model=FleetResponse)
async def list_agents(request: Request) -> FleetResponse:
    """List the fleet."""
    settings = get_settings()
    if "score_entities" in getattr(request.app.state, "tables", ()):
        return FleetResponse(
            agents=[
                FleetMember(
                    id="scorecard",
                    label="Score local",
                    purpose="Explicar nivel, evolución y evidencia de empresa o grupo",
                    rules=[
                        "Mismo motor y pesos que el visor",
                        "Lecturas locales hasta el mes seleccionado",
                        "Confianza es evidencia, no probabilidad",
                    ],
                    tools=[
                        {"name": name, "does": description}
                        for name, description in (
                            ("history", "Historial del score"),
                            ("cash", "Flujos y caja observados"),
                            ("erp", "Pendientes ERP estimados"),
                            ("debt", "Servicio de deuda observado"),
                            ("members", "Empresas del perímetro registrado"),
                        )
                    ],
                )
            ],
            model=settings.llm_model if settings.helmcode_api_key else None,
        )
    return FleetResponse(
        agents=list(ROSTER), model=settings.llm_model if settings.helmcode_api_key else None
    )


@router.post("/chats")
def create_chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """Answer one question as a stream of server-sent events: plan, agents, tokens, done."""

    def events() -> Iterator[str]:
        local = "score_entities" in getattr(request.app.state, "tables", ())
        if local:
            profile = getattr(request.app.state, "score_profile", None) or {}
            stream = run_local_chat(
                body, request.app.state.db, get_settings(), profile.get("config")
            )
        else:
            stream = run_chat(body, request.app.state.db, get_settings())
        for event in stream:
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

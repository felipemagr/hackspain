"""The alert rule book: who is told, and where, when the monitor fires."""

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from xray.agents.llm import build_llm
from xray.agents.notifier import parse_rules
from xray.scoring.rules import RULES_FILE, Rule, add_rule, load_rules, remove_rule
from xray.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["alerts"])


class RuleRequest(BaseModel):
    """A request in plain words, and the group the user is looking at for "this group"."""

    text: str
    group_id: str | None = None


@router.get("/alert-rules", response_model=list[Rule])
async def list_alert_rules() -> list[Rule]:
    """The rules in force, oldest first."""
    return load_rules(get_settings().serving_dir / RULES_FILE)


@router.post("/alert-rules", response_model=list[Rule], status_code=status.HTTP_201_CREATED)
def create_alert_rules(body: RuleRequest) -> list[Rule]:
    """Read a request such as "email me when GROUP_0220 starts falling" into rules, one per
    channel asked for, and save them."""
    settings = get_settings()
    rules = parse_rules(body.text, body.group_id, build_llm(settings, reasoning_effort="low"))
    if not rules:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No channel in the request: say slack or email",
        )
    return [add_rule(settings.serving_dir / RULES_FILE, rule) for rule in rules]


@router.delete("/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: int) -> Response:
    """Drop one rule."""
    if not remove_rule(get_settings().serving_dir / RULES_FILE, rule_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

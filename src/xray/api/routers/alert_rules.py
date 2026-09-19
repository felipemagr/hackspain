"""The alert rule book: who is told, and where, when the monitor fires."""

import smtplib

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from xray.agents.fleet import spelled
from xray.agents.llm import build_llm
from xray.agents.notifier import parse_request
from xray.integrations.email import send_email
from xray.integrations.slack import send_slack
from xray.scoring.rules import (
    RULES_FILE,
    Channel,
    Rule,
    Urgency,
    add_rule,
    load_rules,
    remove_rule,
    update_rule,
)
from xray.settings import get_settings

router = APIRouter(prefix="/api/v1", tags=["alerts"])

NOT_CONFIGURED = {
    "slack": "Slack is not configured on the server: set XRAY_SLACK_WEBHOOK_URL in .env",
    "email": "Email is not configured on the server: set XRAY_SMTP_HOST, XRAY_SMTP_USER and "
    "XRAY_SMTP_PASSWORD in .env",
}


class RuleRequest(BaseModel):
    """A request in plain words, and the group the user is looking at for "this group"."""

    text: str
    group_id: str | None = None


class RuleChanges(BaseModel):
    """The fields the alarms panel can change. Only the ones sent are touched."""

    enabled: bool | None = None
    channel: Channel | None = None
    email_to: str | None = None
    min_urgency: Urgency | None = None
    min_severity: float | None = None
    level_above: float | None = None
    level_below: float | None = None
    groups: list[str] | None = None


@router.get("/alert-rules", response_model=list[Rule])
async def list_alert_rules() -> list[Rule]:
    """The rules in force, oldest first."""
    return load_rules(get_settings().serving_dir / RULES_FILE)


@router.post("/alert-rules", response_model=list[Rule], status_code=status.HTTP_201_CREATED)
def create_alert_rules(body: RuleRequest, request: Request) -> list[Rule]:
    """Read a request such as "email me when GROUP_0220 starts falling" into rules, one per
    channel asked for, and save them."""
    settings = get_settings()
    asked = parse_request(body.text, body.group_id, build_llm(settings, reasoning_effort="low"))
    if not asked:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No alert asked for: say what to watch and where, slack or email",
        )
    if open_question := next((p for p in asked if p.question()), None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Not saved: {open_question.wanted()}. {open_question.question()}",
        )
    # Group ids as the tables spell them (0130 becomes GROUP_0130), when the tables are loaded.
    if "groups" in getattr(request.app.state, "tables", ()):
        cursor = request.app.state.db.cursor()
        asked = [
            p.model_copy(
                update={"groups": list(dict.fromkeys(spelled(cursor, g) for g in p.groups))}
            )
            for p in asked
        ]
    return [add_rule(settings.serving_dir / RULES_FILE, p.rule(body.text)) for p in asked]


@router.patch("/alert-rules/{rule_id}", response_model=Rule)
async def change_alert_rule(rule_id: int, body: RuleChanges) -> Rule:
    """Switch a rule on or off, or change what it watches and where it goes."""
    changes = body.model_dump(exclude_unset=True)
    if changes.get("channel") == "slack":
        changes["email_to"] = None
    rule = update_rule(get_settings().serving_dir / RULES_FILE, rule_id, changes)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.delete("/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(rule_id: int) -> Response:
    """Drop one rule."""
    if not remove_rule(get_settings().serving_dir / RULES_FILE, rule_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/alert-rules/{rule_id}/test", status_code=status.HTTP_204_NO_CONTENT)
def test_alert_rule(rule_id: int) -> Response:
    """Send a test message down the rule's channel, so the user sees where alerts will land."""
    rules = load_rules(get_settings().serving_dir / RULES_FILE)
    rule = next((r for r in rules if r.id == rule_id), None)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    subject = "Lighthouse: test alert"
    body = f"{rule.describe()}. Alerts for this rule will arrive here."
    try:
        if rule.channel == "slack":
            sent = send_slack(f"{subject}\n{body}")
        else:
            sent = send_email(subject, body, to=rule.email_to)
    except (httpx.HTTPError, OSError, smtplib.SMTPException) as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The {rule.channel} channel refused the test: {str(e)[:120]}",
        ) from e
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=NOT_CONFIGURED[rule.channel],
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

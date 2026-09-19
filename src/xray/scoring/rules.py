"""Who is told, and where, when the monitor fires: the rule book behind `notify --channel rules`.

A rule names a channel, the least urgent alert it wants, an optional severity floor and the groups
it watches. Urgency is read off the alert row, so the same alert means the same thing to every
rule: `critical` when a group enters `falling`, `warning` for any other move down, `info` for a
move up or a bump that reverted.

The book is one JSON file next to the serving tables: the chat writes it from inside the API and
`notify.dispatch` reads it from the pipeline, and both see the same directory.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

RULES_FILE = "alert_rules.json"
URGENCIES = ("info", "warning", "critical")
Urgency = Literal["info", "warning", "critical"]
Channel = Literal["slack", "email"]

WANTS = {
    "info": "every alert",
    "warning": "warning and critical alerts",
    "critical": "critical alerts",
}


def urgency_of(direction: str, state_to: str) -> Urgency:
    """How bad an alert row is, from the columns every row has."""
    if direction == "up":
        return "info"
    return "critical" if state_to == "falling" else "warning"


class Rule(BaseModel):
    """One standing request: this channel, for alerts at least this urgent, on these groups."""

    text: str
    channel: Channel
    id: int | None = None
    min_urgency: Urgency = "info"
    min_severity: float | None = None
    groups: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def matches(self, urgency: str, severity: float, group_id: str) -> bool:
        return (
            URGENCIES.index(urgency) >= URGENCIES.index(self.min_urgency)
            and (self.min_severity is None or severity >= self.min_severity)
            and (not self.groups or group_id in self.groups)
        )

    def describe(self) -> str:
        """The rule in one line, as the chat and the log show it."""
        who = ", ".join(self.groups) if self.groups else "any group"
        floor = f", severity {self.min_severity:g} or more" if self.min_severity is not None else ""
        return f"{self.channel.capitalize()} gets {WANTS[self.min_urgency]} on {who}{floor}"


def load_rules(path: Path) -> list[Rule]:
    """The rules in force, oldest first. No file, no rules."""
    if not path.exists():
        return []
    return [Rule.model_validate(entry) for entry in json.loads(path.read_text())]


def add_rule(path: Path, rule: Rule) -> Rule:
    """Append a rule to the book and return it with its id."""
    rules = load_rules(path)
    rule = rule.model_copy(update={"id": max((r.id for r in rules if r.id), default=0) + 1})
    _write(path, [*rules, rule])
    return rule


def remove_rule(path: Path, rule_id: int) -> bool:
    """Drop one rule. False when no rule has that id."""
    rules = load_rules(path)
    kept = [r for r in rules if r.id != rule_id]
    if len(kept) == len(rules):
        return False
    _write(path, kept)
    return True


def _write(path: Path, rules: list[Rule]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.model_dump() for r in rules], indent=2) + "\n")

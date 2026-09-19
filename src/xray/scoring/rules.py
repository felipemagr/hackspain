"""Who is told, and where, when the monitor fires: the rule book behind `notify --channel rules`.

A rule names a channel, what it waits for and the groups it watches. It waits for one of two
things: the monitor's alerts from an urgency up, with an optional severity floor, or the level
crossing a line (`level_above`, `level_below`). Urgency is read off the alert row, so the same
alert means the same thing to every rule: `critical` when a group enters `falling`, `warning` for
any other move down, `info` for a move up or a bump that reverted.

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


class Trigger(BaseModel):
    """What a rule waits for: alerts from an urgency up, or the level crossing a line."""

    min_urgency: Urgency = "info"
    min_severity: float | None = None
    level_above: float | None = None
    level_below: float | None = None
    groups: list[str] = Field(default_factory=list)

    def lines(self) -> list[tuple[str, float]]:
        """The level lines this rule watches, as (side, line). Empty for a monitor rule."""
        drawn = [("above", self.level_above), ("below", self.level_below)]
        return [(side, line) for side, line in drawn if line is not None]

    def watches(self, group_id: str) -> bool:
        return not self.groups or group_id in self.groups

    def matches(self, urgency: str, severity: float, group_id: str) -> bool:
        """Whether a monitor alert is wanted. A level rule wants none: it has its own messages."""
        return (
            not self.lines()
            and URGENCIES.index(urgency) >= URGENCIES.index(self.min_urgency)
            and (self.min_severity is None or severity >= self.min_severity)
            and self.watches(group_id)
        )

    def wanted(self) -> str:
        """What is waited for, in words: the object of "Slack gets ..."."""
        who = ", ".join(self.groups) if self.groups else "any group"
        if lines := self.lines():
            return f"a message when {who} goes {' or '.join(f'{s} {v:g}' for s, v in lines)}"
        floor = f", severity {self.min_severity:g} or more" if self.min_severity is not None else ""
        return f"{WANTS[self.min_urgency]} on {who}{floor}"


class Rule(Trigger):
    """One standing request: this channel, waiting for this, on these groups."""

    text: str
    channel: Channel
    id: int | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def describe(self) -> str:
        """The rule in one line, as the chat and the log show it."""
        return f"{self.channel.capitalize()} gets {self.wanted()}"


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

"""Turns "tell me on Slack when a group starts falling" into rules of the alert book.

The model reads the request into the fields of one rule per channel asked for; without a model,
or when it fails, a few patterns do. What the notifier applies afterwards is the rule, never the
sentence, and every rule is shown back in full before any month lands.
"""

import logging
import re
from itertools import pairwise

from pydantic import BaseModel, Field

from xray.agents.llm import LLM, complete_json
from xray.scoring.rules import Channel, Rule, Urgency

logger = logging.getLogger(__name__)

PROMPT = """You set up alert delivery inside a financial health monitor. The user says where they
want to be told, about which groups, and how bad a move has to be. Answer with JSON only, one
entry per channel they ask for, an empty list when they are not asking to be told anything (for
instance when they ask which rules exist):
{"rules": [{"channel": "slack", "min_urgency": "warning", "min_severity": null, "groups": [],
"this_group": false}]}

channel: slack or email.
min_urgency: critical when they want structural decline only, a group entering falling; warning
for any move down, bending and sharp one-month drops included; info for everything, improvement
and reverted bumps too. info when they do not say.
min_severity: the number when they give a severity floor, else null.
groups: the group ids named, such as GROUP_0220. Empty for the whole portfolio.
this_group: true when they say this group, this company or the like."""

CHANNEL_WORDS = (
    (re.compile(r"slack", re.I), "slack"),
    (re.compile(r"e-?mail|correo", re.I), "email"),
)
WARNING_WORDS = re.compile(r"bend|warn|drop|deterior|down|flex|baj|empeor|worse", re.I)
CRITICAL_WORDS = re.compile(r"fall|critical|cr[ií]t|caer|ca[ií]da|\bcae|collapse|hund|struct", re.I)
SEVERITY = re.compile(r"severity\D{0,12}?(\d+(?:\.\d+)?)", re.I)
# A group id is a word with a digit and a letter in it: GROUP_0220, not 20.
GROUP = re.compile(r"\b(?=\w*\d)(?=\w*[A-Za-z])\w+\b")
THIS_GROUP = re.compile(r"this (group|company|one)|est[ae] (grupo|empresa|compa)", re.I)


class Parsed(BaseModel):
    """The request read into the fields of one rule."""

    channel: Channel
    min_urgency: Urgency = "info"
    min_severity: float | None = None
    groups: list[str] = Field(default_factory=list)
    this_group: bool = False


class ParsedRequest(BaseModel):
    rules: list[Parsed] = Field(default_factory=list)


def parse_by_patterns(text: str) -> list[Parsed]:
    """The fallback without a model: channel and urgency words, a severity figure, group ids.

    A sentence naming two channels is cut where the second one starts, so each channel reads
    the words around it: "slack me when a group falls, and email me everything on GROUP_0220".
    """
    starts = sorted(m.start() for pattern, _ in CHANNEL_WORDS for m in pattern.finditer(text))
    if not starts:
        return []
    return [_parse_part(text[a:b]) for a, b in pairwise([0, *starts[1:], len(text)])]


def _parse_part(text: str) -> Parsed:
    channel = next(name for pattern, name in CHANNEL_WORDS if pattern.search(text))
    if WARNING_WORDS.search(text):
        urgency = "warning"
    elif CRITICAL_WORDS.search(text):
        urgency = "critical"
    else:
        urgency = "info"
    severity = SEVERITY.search(text)
    return Parsed(
        channel=channel,
        min_urgency=urgency,
        min_severity=float(severity.group(1)) if severity else None,
        groups=GROUP.findall(text),
        this_group=bool(THIS_GROUP.search(text)),
    )


def parse_rules(text: str, this_group: str | None, llm: LLM | None) -> list[Rule]:
    """The rules the request asks for, none when it asks for none. Model first, patterns after.

    Args:
        text: The request as typed.
        this_group: The group the chat is open on, for "this group".
        llm: The model, or None to read by patterns.
    """
    parsed = None
    if llm:
        try:
            parsed = complete_json(llm, PROMPT, text, ParsedRequest).rules
        except Exception as e:  # the patterns still read the plain cases
            logger.warning("Rule parser failed, using patterns: %s", e)
    if parsed is None:
        parsed = parse_by_patterns(text)
    return [
        Rule(
            text=text,
            channel=p.channel,
            min_urgency=p.min_urgency,
            min_severity=p.min_severity,
            groups=list(
                dict.fromkeys([*p.groups, *([this_group] if p.this_group and this_group else [])])
            ),
        )
        for p in parsed
    ]

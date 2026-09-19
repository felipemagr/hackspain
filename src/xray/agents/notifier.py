"""Turns "tell me on Slack when a group starts falling" into rules of the alert book.

The model reads the request into the fields of one rule per channel asked for; without a model,
or when it fails, a few patterns do. A request that says what to watch but not where comes back
without a channel, so the chat can ask. What the notifier applies afterwards is the rule, never
the sentence, and every rule is shown back in full before any month lands.
"""

import logging
import re
from itertools import pairwise

from pydantic import BaseModel, Field

from xray.agents.llm import LLM, complete_json
from xray.scoring.rules import Channel, Rule, Trigger

logger = logging.getLogger(__name__)

PROMPT = """You set up alert delivery inside a financial health monitor. The user says what to
watch, about which groups, and where to be told. Answer with JSON only: one entry per channel
they ask for; one entry with channel null when they ask to be told but not where; {"rules": []}
when they are not asking to be told about a move in a score (a question about the rules, a
request to email or share this answer, pasted text):
{"rules": [{"channel": "slack", "email_to": null, "min_urgency": "warning", "min_severity": null,
"level_above": null, "level_below": null, "groups": [], "this_group": false}]}

channel: slack or email. null when they do not say where.
email_to: the email address when they write one; the channel is then email. null otherwise.
level_above, level_below: the figure when they want to know when the score, level or health goes
above or below one (crosses, reaches, exceeds, drops under). A rule with one of these leaves
min_urgency at info and min_severity null.
min_urgency: critical when they want structural decline only, a group entering falling; warning
for any move down, bending and sharp one-month drops included; info for everything, improvement
and reverted bumps too. info when they do not say.
min_severity: the number only when they say severity. A score or level figure is level_above or
level_below, never this.
groups: the group ids named, spelled as the tables spell them: GROUP_0130, also when the user
writes 0130 or group 130. Empty for the whole portfolio.
this_group: true when they say this group, this company or the like.
When an earlier request is given, the message answers where to send it, a channel or an
address: read the rest from the earlier request."""

CHANNEL_WORDS = (
    (re.compile(r"slack", re.I), "slack"),
    (re.compile(r"e-?mail|correo", re.I), "email"),
)
EMAIL_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Someone asking to be told, as opposed to asking about the rules or pasting text.
INTENT = re.compile(
    r"alarm|alert me|alerta|notif|av[ií]s|tell me|let me know|\bping|warn me|slack me|e-?mail me"
    r"|mail me|\bcrea|set up|configura|quiero|\bwant",
    re.I,
)
WARNING_WORDS = re.compile(r"bend|warn|drop|deterior|down|flex|baj|empeor|worse", re.I)
CRITICAL_WORDS = re.compile(r"fall|critical|cr[ií]t|caer|ca[ií]da|\bcae|collapse|hund|struct", re.I)
SEVERITY = re.compile(r"severity\D{0,12}?(\d+(?:\.\d+)?)", re.I)
LEVEL_ABOVE = re.compile(
    r"(?:above|over|exceeds?|more than|higher than|greater than|reach(?:es)?|hits?|pass(?:es)?"
    r"|por encima de|supera|superior a|llega a|m[aá]s de)\s+(\d+(?:\.\d+)?)\b",
    re.I,
)
LEVEL_BELOW = re.compile(
    r"(?:below|under|beneath|less than|lower than|drops? (?:to|under)|falls? (?:to|under)"
    r"|por debajo de|baja de|menos de|inferior a)\s+(\d+(?:\.\d+)?)\b",
    re.I,
)
# A group id is a word with a digit and a letter in it: GROUP_0220, not 20. A bare number is
# one only after "the" or "group": "the 0130", "grupo 130".
GROUP = re.compile(r"\b(?=\w*\d)(?=\w*[A-Za-z])\w+\b")
BARE_GROUP = re.compile(r"\b(?:the|group|grupo|el|la)\s+(\d{3,4})\b", re.I)
THIS_GROUP = re.compile(r"this (group|company|one)|est[ae] (grupo|empresa|compa)", re.I)


class Parsed(Trigger):
    """The request read into the fields of one rule. No channel when it does not say where."""

    channel: Channel | None = None
    email_to: str | None = None
    this_group: bool = False

    def question(self) -> str | None:
        """What the request still has to say before it can be saved, or None."""
        if self.channel is None:
            return "Slack or email? For email, say the address too."
        if self.channel == "email" and not self.email_to:
            return "Which email address?"
        return None

    def rule(self, text: str) -> Rule:
        """The rule to save. `question()` must be None."""
        return Rule(text=text, **self.model_dump(exclude={"this_group"}))


class ParsedRequest(BaseModel):
    rules: list[Parsed] = Field(default_factory=list)


def parse_by_patterns(text: str) -> list[Parsed]:
    """The fallback without a model: channel and urgency words, a level or severity figure,
    group ids. Nothing unless the text asks to be told.

    A sentence naming two channels is cut where the second one starts, so each channel reads
    the words around it: "slack me when a group falls, and email me everything on GROUP_0220".
    """
    if not INTENT.search(text):
        return []
    starts = sorted(m.start() for pattern, _ in CHANNEL_WORDS for m in pattern.finditer(text))
    if not starts:
        return [_parse_part(text)]
    return [_parse_part(text[a:b]) for a, b in pairwise([0, *starts[1:], len(text)])]


def _parse_part(text: str) -> Parsed:
    address = EMAIL_ADDRESS.search(text)
    # The address is read first and taken out: "p711" in it is not a group.
    text = EMAIL_ADDRESS.sub(" ", text)
    channel = next((name for pattern, name in CHANNEL_WORDS if pattern.search(text)), None)
    if WARNING_WORDS.search(text):
        urgency = "warning"
    elif CRITICAL_WORDS.search(text):
        urgency = "critical"
    else:
        urgency = "info"
    severity, above, below = (p.search(text) for p in (SEVERITY, LEVEL_ABOVE, LEVEL_BELOW))
    return Parsed(
        channel="email" if address else channel,
        email_to=address.group(0) if address else None,
        min_urgency="info" if above or below else urgency,
        min_severity=float(severity.group(1)) if severity else None,
        level_above=float(above.group(1)) if above else None,
        level_below=float(below.group(1)) if below else None,
        groups=[*GROUP.findall(text), *BARE_GROUP.findall(text)],
        this_group=bool(THIS_GROUP.search(text)),
    )


def parse_request(
    text: str, this_group: str | None, llm: LLM | None, earlier: str = ""
) -> list[Parsed]:
    """What the request asks for, none when it asks for nothing. Model first, patterns after.

    Args:
        text: The request as typed.
        this_group: The group the chat is open on, for "this group".
        llm: The model, or None to read by patterns.
        earlier: The request the user was asked where to send, when this message answers that.
    """
    parsed = None
    if llm:
        user = f"Earlier request:\n{earlier}\n\nNow the user says:\n{text}" if earlier else text
        try:
            parsed = complete_json(llm, PROMPT, user, ParsedRequest).rules
        except Exception as e:  # the patterns still read the plain cases
            logger.warning("Rule parser failed, using patterns: %s", e)
    if parsed is None:
        parsed = parse_by_patterns(f"{earlier} {text}" if earlier else text)
    return [
        p.model_copy(update={"groups": list(dict.fromkeys([*p.groups, this_group]))})
        if p.this_group and this_group
        else p
        for p in parsed
    ]

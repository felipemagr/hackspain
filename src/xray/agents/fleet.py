"""The chat: a planner guides a small fleet over one group and month, a writer answers.

Agents are cut by what they do to the scorecard, not by who is asking: read it, go under it,
simulate it, place it in the portfolio, read the world around it. The planner works out who is
asking (the lens) and tells each agent what to look for and which tools to run.

Every agent is a purpose, a set of rules and a set of tools. The rules are code and are shown on
screen. Each tool call is an event, so the screen can show what every agent is doing while it
does it. SQL produces the figures. Where the model thinks or writes, its figures are checked
against the tool output it was given: `untraced_figures`.

`run_chat` yields plain dict events: planning, plan, agent, step, dispatch, suggestion, writing,
token, check, done. Agents run in threads and report through one queue. Searches run in parallel but
model calls go one at a time: Helmcode stalls concurrent requests on one key.
"""

import csv
import logging
import queue
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, Field, field_validator

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.cache import JsonCache
from xray.agents.context_retrieval import ContextRetrievalAgent
from xray.agents.llm import LLM, build_llm, complete_json
from xray.agents.peers import PeersAgent, SectorAgent
from xray.scoring.anchors import CAP_LEVEL, CAP_PILLAR_SCORE, CAP_PILLARS, PILLAR_WEIGHTS
from xray.settings import Settings

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 2000
MAX_HISTORY_TURNS = 6
DRIVER_WINDOW_MONTHS = 6
CUSTOMERS_SHOWN = 6
MIN_PAID_INVOICES = 6
# Investor screen. A search fund buys one steady, high-margin company; lenders want cover.
SEARCH_FUND_MARGIN = 0.15
SEARCH_FUND_LEVEL = 60
MARGIN_STEADY = 0.05
MIN_COVER = 1.5

# Mirrors of scoring/offer.py, which needs pandas and the API image has none. A test ties them.
LIMIT_CURVE = ((40, 90), (0.2, 1.5))
MIN_COMPOUND = 40.0
TREND_MONTHS_PRICED = 4
# Counts and small ordinals are words, not figures to trace.
FREE_FIGURE_MAX = 12

Lens = Literal["cfo", "lender", "investor"]


class Tool(BaseModel):
    name: str
    does: str


class FleetMember(BaseModel):
    id: str
    label: str
    purpose: str
    rules: list[str]
    tools: list[Tool]
    thinks: bool = False


ROSTER: tuple[FleetMember, ...] = (
    FleetMember(
        id="scorecard",
        label="Scorecard",
        purpose="Why this score, and since when.",
        rules=[
            "Every figure is read from the score tables, never produced by the model.",
            "A pillar the group has no data for is declared, not imputed.",
            "A level is judged against the group's own history, not only the 0-100 scale.",
            "One bad month is a bump: it never triggers a limit review on its own.",
            "Anticipation is measured against the month the tier actually changed.",
        ],
        tools=[
            Tool(name="pillars_at", does="level, state, trend and the five pillars this month"),
            Tool(name="drivers_window", does="which pillars moved the level over six months"),
            Tool(name="own_history_rank", does="where this level sits in the group's own months"),
            Tool(name="alerts_for", does="alerts fired up to this month, with their drivers"),
        ],
    ),
    FleetMember(
        id="ledger",
        label="Ledger",
        purpose="The invoices, cash and debt under the score.",
        thinks=True,
        rules=[
            f"A customer needs {MIN_PAID_INVOICES} paid invoices before its lateness counts.",
            "A customer is judged only on how it paid this group: ids do not link across groups.",
            "Open and overdue are rebuilt as of the month, never read from the final snapshot.",
            "Amounts are in euros at the average rate of the year each invoice was issued.",
            "Free cash flow is taken before debt service: what an enterprise value discounts.",
            f"Debt capacity keeps debt service covered {MIN_COVER}x by operating cash.",
        ],
        tools=[
            Tool(name="concentration", does="share of billing on the largest customers"),
            Tool(name="payer_scores", does="days late, its change and a 0-100 score per customer"),
            Tool(name="overdue_ranked", does="who to chase first: overdue amount and its age"),
            Tool(name="cash_profile", does="margin, its steadiness and free cash flow before debt"),
            Tool(name="debt_capacity", does="extra debt service the cash flow could carry"),
        ],
    ),
    FleetMember(
        id="simulator",
        label="Simulator",
        purpose="What a move does to the level and the line.",
        rules=[
            "The limit is priced on level plus four months of trend.",
            "A what-if runs the engine's own contract: same weights, same cap under 25.",
            "Anything that moves money leaves as a draft for a person to sign.",
        ],
        tools=[
            Tool(name="offer_at", does="limit, price and change on last month"),
            Tool(name="actions_ranked", does="next moves ranked by expected gain in points"),
            Tool(name="what_if", does="the level and the limit after moving a pillar"),
        ],
    ),
    FleetMember(
        id="peers",
        label="Peers",
        purpose="Where the group sits in the portfolio.",
        thinks=True,
        rules=[
            "Both sides of a comparison are read at the same month.",
            f"Search fund screen: one company, operating margin of {SEARCH_FUND_MARGIN:.0%} or "
            f"more, steady for a year, level {SEARCH_FUND_LEVEL} or higher, not bending or falling.",  # noqa: E501
            "The data has no sector and no valuation multiples: no enterprise value is estimated, "
            "and comparables are by country and size only.",
        ],
        tools=[
            Tool(name="standing", does="rank of the level and the trend among scored groups"),
            Tool(
                name="compare",
                does="this group against another one the question names, pillar by pillar",
            ),
            Tool(name="screen", does="the search fund test, and how many groups pass it"),
            Tool(name="comparables", does="groups of similar size in the country, for a roll-up"),
        ],
    ),
    FleetMember(
        id="macro",
        label="Macro",
        purpose="The country around the group, read once.",
        thinks=True,
        rules=[
            "Only dated facts with a source.",
            "One read per country, kept for a week: the next group there costs no tokens.",
        ],
        tools=[
            Tool(name="cache.read", does="the country read, when one is younger than a week"),
            Tool(name="exa.search", does="recent news on companies in the country"),
            Tool(name="model.read", does="extracts dated facts from the pages found"),
        ],
    ),
    FleetMember(
        id="market",
        label="Market",
        purpose="A named company: its peers and its press.",
        thinks=True,
        rules=[
            "Runs only for a real company the user names: groups are anonymous ids.",
            "Only dated facts with a source.",
        ],
        tools=[
            Tool(name="exa.search", does="competitors and their recent news"),
            Tool(name="tavily.search", does="press and registry on the named company"),
            Tool(name="model.read", does="extracts dated facts from the pages found"),
        ],
    ),
)
MEMBERS = {member.id: member for member in ROSTER}
INVOICE_TOOLS = ("concentration", "payer_scores", "overdue_ranked")
CASH_TOOLS = ("cash_profile", "debt_capacity")

PLANNER_PROMPT = """You direct a fleet of agents inside a financial health monitor. Anyone may be
asking: the group's CFO, a lender deciding on a credit line, an investor screening a target.
Work out who is asking and what the answer needs, then guide each agent you dispatch: tell it
what to look for, and which of its tools to run. Dispatch only what the answer needs.
`scorecard` always runs: every other agent works from what it reads.

Agents and their tools:
{roster}

The group has invoice data: {has_erp}. Without it the invoice tools of `ledger` read nothing.
Groups are anonymous ids. Set `company` only when the user names a real-world company:
`market` runs only then. {compare}
Set `what_if` when the user asks what a change would do: pillar to points moved, pillars are
liquidity, cash_generation, payment_discipline, collections, debt_burden.
Set `wants_action` when the user asks what to do, who to chase or what to change.

Answer with JSON only:
{{"lens": "cfo", "purpose": "three to six words on what the question is for",
"agents": ["scorecard", "ledger"], "asks": {{"ledger": "up to twelve words on what to look for"}},
"tools": {{"ledger": ["overdue_ranked"]}}, "company": null, "what_if": {{}},
"wants_action": false}}
`lens` is one of cfo, lender, investor."""

INTERPRET_PROMPT = """You are the {label} agent inside a financial health monitor. The planner
asks you: "{ask}". Answer it in at most two sentences from the tool output below. Copy every
figure exactly as it is written there: never compute, convert or round a new one. If the output
does not hold the answer, say so. Plain text, in the language of the ask."""

WRITER_PROMPT = """You are X Ray, the analyst inside a financial health monitor. The person
asking is read as: {lens}. Answer the question using only the agent reports below. Lead with the
answer in one sentence. Then the evidence: which pillar moved, since when, with the numbers from
the reports. When the question is about what to do, end with the ranked moves. Say plainly when
the reports do not hold the answer.

Every figure you write is checked against the reports after you finish: copy figures exactly as
they are written there, and never compute, convert or round a new one.

States: a bump is one bad month that recovers; bending is a sustained early decline while the
level still looks fine; falling is structural decline; improving is a sustained rise. The
current state is the one Scorecard reports. A draft suggestion, when present, is shown to the
user under your answer: refer to it, do not repeat it.

Plain text, short paragraphs, no markdown, no bullets, no headings. At most 150 words.
Answer in the language of the question."""

PILLAR_LABELS = {
    "liquidity": "liquidity",
    "cash_generation": "cash generation",
    "payment_discipline": "payment discipline",
    "collections": "collections",
    "debt_burden": "debt burden",
}
ACTION_WORDS = re.compile(r"\b(do|should|chase|hacer|hacemos|hago|cobr|reclam|priorit)", re.I)
# Group ids carry a digit: only those words are looked up.
MENTION = re.compile(r"\b\w*\d\w*\b")
# Digits inside an id (GROUP_0220) are a name, not a figure.
FIGURE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
# The planner's fallback when there is no model: purpose, pattern, lens, agent to its tools.
PURPOSE_RULES: tuple[tuple[str, str, Lens, dict[str, list[str]]], ...] = (
    (
        "screening a target",
        r"invest|buy|acqui|search fund|roll.?up|leverage|comprar|inver",
        "investor",
        {"ledger": list(CASH_TOOLS), "peers": ["screen", "comparables"]},
    ),
    (
        "collecting from customers",
        r"customer|client|pay(s|ing)? (me|us)|late|chase|cobr|moros",
        "cfo",
        {"ledger": list(INVOICE_TOOLS)},
    ),
    (
        "the credit line",
        r"credit|line|limit|financ|anticip|circulante|do this week|what if",
        "cfo",
        {"simulator": []},
    ),
    ("us or the market", r"sector|market|compet|macro|econom|mercado", "cfo", {"macro": []}),
    ("against the portfolio", r"peer|compare|rank|portfolio|compar|cartera", "cfo", {"peers": []}),
)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """One question about one group at one month, with the recent turns for follow-ups."""

    message: str
    group_id: str
    month: str
    history: list[ChatTurn] = Field(default_factory=list)
    currency: Literal["EUR", "USD"] = "EUR"

    @field_validator("message", mode="before")
    @classmethod
    def _trim(cls, value: str) -> str:
        return str(value).strip()[:MAX_MESSAGE_CHARS]

    @field_validator("history", mode="after")
    @classmethod
    def _recent(cls, value: list[ChatTurn]) -> list[ChatTurn]:
        return value[-MAX_HISTORY_TURNS:]


class Plan(BaseModel):
    """Who is asking, which agents answer, and what the planner tells each one."""

    agents: list[str]
    lens: Lens = "cfo"
    purpose: str = "why the score moved"
    asks: dict[str, str] = Field(default_factory=dict)
    tools: dict[str, list[str]] = Field(default_factory=dict)
    company: str | None = None
    compare: str | None = None
    what_if: dict[str, float] = Field(default_factory=dict)
    wants_action: bool = False


@dataclass
class Step:
    """One tool call in flight. Set `output` before the block ends."""

    output: str = ""


@dataclass
class AgentContext:
    """What an agent needs to run and to report what it is doing."""

    agent_id: str
    request: ChatRequest
    snapshot: ScoreSnapshot
    db: duckdb.DuckDBPyConnection
    settings: Settings
    llm: LLM | None
    plan: Plan
    has_erp: bool
    emit: Callable[[dict], None]
    facts: dict[str, Any] = field(default_factory=dict)
    steps: int = 0

    @property
    def ask(self) -> str:
        return self.plan.asks.get(self.agent_id, "")

    def wants(self, tool: str) -> bool:
        """The planner may narrow an agent to some of its tools. No list means all of them."""
        wanted = self.plan.tools.get(self.agent_id)
        return not wanted or tool in wanted

    def money(self, eur: float, signed: bool = False) -> str:
        """An amount held in euros, shown in the currency the user picked, at the month's year."""
        code = self.request.currency
        value = eur * display_rate(code, int(self.request.month[:4]))
        return f"{value:+,.0f} {code}" if signed else f"{value:,.0f} {code}"

    def query(self, sql: str, params: list | None = None) -> list[tuple]:
        """Run SQL with (group_id, month) bound unless other params are given."""
        bound = [self.request.group_id, self.request.month] if params is None else params
        return self.db.execute(sql, bound).fetchall()

    @contextmanager
    def tool(self, name: str, **inputs: Any) -> Iterator[Step]:
        self.steps += 1
        n, t0, step = self.steps, time.monotonic(), Step()
        shown = ", ".join(f"{key}={value}" for key, value in inputs.items())
        base = {"type": "step", "agent": self.agent_id, "n": n, "tool": name, "input": shown}
        self.emit(base | {"status": "running"})
        try:
            yield step
        except Exception as e:
            self.emit(base | {"status": "failed", "output": str(e)[:160], "ms": _ms(t0)})
            raise
        self.emit(base | {"status": "done", "output": step.output, "ms": _ms(t0)})


class SerialLLM:
    """One model call at a time across threads, each one a traced step."""

    _lock = threading.Lock()

    def __init__(self, llm: LLM, ctx: AgentContext):
        self.llm = llm
        self.ctx = ctx

    def complete(self, system: str, user: str) -> str:
        with self.ctx.tool("model.read", chars=len(user)) as step, self._lock:
            answer = self.llm.complete(system, user)
            step.output = f"{len(answer)} characters of extracted facts"
            return answer


def run_chat(
    request: ChatRequest, db: duckdb.DuckDBPyConnection, settings: Settings
) -> Iterator[dict]:
    """Plan, dispatch, follow up once, suggest, write, check the figures."""
    started = time.monotonic()
    snapshot, has_erp = load_snapshot(db.cursor(), request.group_id, request.month)
    if snapshot is None:
        yield {"type": "error", "message": "No score for that group and month."}
        return
    llm = build_llm(settings, reasoning_effort="low")

    yield {"type": "planning"}
    plan = make_plan(request, snapshot, has_erp, llm, mentioned_group(request, db.cursor()))
    yield {
        "type": "plan",
        "purpose": plan.purpose,
        "lens": plan.lens,
        "company": plan.company,
        "compare": plan.compare,
        "agents": [{"id": a, "reason": plan.asks.get(a, "")} for a in plan.agents],
    }

    events: queue.Queue[dict] = queue.Queue()
    reports: dict[str, AgentReport] = {}
    facts: dict[str, Any] = {}
    waves = [list(plan.agents)]
    with ThreadPoolExecutor(max_workers=len(ROSTER)) as pool:
        while waves:
            running: dict[Future, str] = {}
            for agent_id in waves.pop():
                ctx = AgentContext(
                    agent_id, request, snapshot, db.cursor(), settings, llm, plan, has_erp,
                    events.put, facts,
                )  # fmt: skip
                yield {"type": "agent", "id": agent_id, "status": "running"}
                running[pool.submit(_timed, AGENTS[agent_id], ctx)] = agent_id
            while running:
                yield from _drain(events)
                for future in [f for f in running if f.done()]:
                    agent_id = running.pop(future)
                    yield from _drain(events)
                    yield _outcome(agent_id, future, reports)
                time.sleep(0.02)
            if follow_up := director_follow_up(plan, reports, facts, has_erp):
                plan.agents.extend(a["id"] for a in follow_up)
                yield {"type": "dispatch", "agents": follow_up}
                waves.append([a["id"] for a in follow_up])

    suggestion = draft_suggestion(plan, facts)
    if suggestion:
        yield {"type": "suggestion"} | suggestion

    yield {"type": "writing"}
    source, answer = writer_input(request, snapshot, plan, reports, suggestion), ""
    try:
        for text in write(plan, reports, source, llm):
            answer += text
            yield {"type": "token", "text": text}
    except Exception as e:  # the trace above already holds the evidence
        logger.warning("Writer failed: %s", e)
        yield {"type": "error", "message": "The writer could not finish. The agent reports stand."}
    else:
        untraced = untraced_figures(answer, source)
        yield {"type": "check", "figures": len(_figures(answer)), "untraced": untraced}
    yield {"type": "done", "ms": _ms(started)}


def mentioned_group(request: ChatRequest, cursor: duckdb.DuckDBPyConnection) -> str | None:
    """The first other group the question names by its id, when it has a score that month."""
    for group_id in MENTION.findall(request.message):
        if group_id == request.group_id:
            continue
        found = cursor.execute(
            "select 1 from scores where group_id = ? and month = cast(? as timestamp)",
            [group_id, request.month],
        ).fetchone()
        if found:
            return group_id
    return None


def make_plan(
    request: ChatRequest,
    snapshot: ScoreSnapshot,
    has_erp: bool,
    llm: LLM | None,
    compare: str | None = None,
) -> Plan:
    """Ask the model who is asking and how to guide the fleet. Without it, or if it fails, rules."""
    plan = None
    if llm:
        roster = "\n".join(
            f"- {m.id}: {m.purpose} Tools: " + "; ".join(f"{t.name} ({t.does})" for t in m.tools)
            for m in ROSTER
        )
        named = f"The question compares it with group {compare}: `peers` runs `compare`."
        system = PLANNER_PROMPT.format(
            roster=roster, has_erp="yes" if has_erp else "no", compare=named if compare else ""
        )
        user = f"Group: {snapshot.name} ({snapshot.country})\nQuestion: {request.message}"
        try:
            plan = complete_json(llm, system, user, Plan)
        except Exception as e:  # a bad plan must not cost the answer
            logger.warning("Planner failed, using rules: %s", e)
    if plan is None:
        plan = Plan(agents=["scorecard"])
        for purpose, pattern, lens, tools in PURPOSE_RULES:
            if re.search(pattern, request.message, re.I):
                plan = Plan(agents=["scorecard", *tools], lens=lens, purpose=purpose, tools=tools)
                break
        plan.wants_action = bool(ACTION_WORDS.search(request.message))

    tools = {
        agent: [t for t in picked if t in {tool.name for tool in MEMBERS[agent].tools}]
        for agent, picked in plan.tools.items()
        if agent in MEMBERS
    }
    wanted = dict.fromkeys(["scorecard", *plan.agents, *(["peers"] if compare else [])])
    if compare and tools.get("peers"):
        tools["peers"] = list(dict.fromkeys([*tools["peers"], "compare"]))
    if not has_erp:
        # Without invoices the ledger still reads cash and debt, when that is what was asked.
        tools["ledger"] = [t for t in tools.get("ledger") or CASH_TOOLS if t in CASH_TOOLS]
        if not tools["ledger"]:
            wanted.pop("ledger", None)
    if not plan.company:
        wanted.pop("market", None)
    known = sorted((a for a in wanted if a in MEMBERS), key=list(MEMBERS).index)
    what_if = {p: points for p, points in plan.what_if.items() if p in PILLAR_LABELS}
    return plan.model_copy(
        update={"agents": known, "tools": tools, "compare": compare, "what_if": what_if}
    )


def director_follow_up(
    plan: Plan, reports: dict[str, AgentReport], facts: dict[str, Any], has_erp: bool
) -> list[dict]:
    """One extra dispatch, decided by rules on what Scorecard found. At most once per question."""
    if facts.get("followed_up") or "scorecard" not in reports:
        return []
    facts["followed_up"] = True
    if facts.get("worst_driver") != "collections" or not has_erp or "ledger" in plan.agents:
        return []
    ask = "collections is dragging the level: who pays late?"
    plan.asks["ledger"] = ask
    plan.tools["ledger"] = list(INVOICE_TOOLS)
    return [{"id": "ledger", "reason": ask}]


def draft_suggestion(plan: Plan, facts: dict[str, Any]) -> dict | None:
    """The one action to put in front of a person. Built from figures, never from the model."""
    if not plan.wants_action:
        return None
    if chase := facts.get("chase"):
        return {
            "agent": "ledger",
            "title": f"Chase {chase['name']} this week",
            "detail": (
                f"{chase['overdue']} overdue, the oldest invoice "
                f"{chase['oldest_overdue_days']} days past due. It is "
                f"{chase['share_of_billing']:.0%} of the last twelve months of billing."
            ),
        }
    if action := facts.get("top_action"):
        return {
            "agent": "simulator",
            "title": f"Act on {PILLAR_LABELS.get(action['pillar'], action['pillar'])}",
            "detail": f"{action['action']} Expected gain {action['gain']:+.1f} points.",
        }
    return None


def writer_input(
    request: ChatRequest,
    snapshot: ScoreSnapshot,
    plan: Plan,
    reports: dict[str, AgentReport],
    suggestion: dict | None,
) -> str:
    """Everything the writer may quote. The figure check reads the same text."""
    sections = [
        f"## {MEMBERS[agent_id].label}\n{report.summary}\n" + "\n".join(report.findings)
        for agent_id, report in reports.items()
    ]
    history = "\n".join(f"{turn.role}: {turn.content}" for turn in request.history)
    draft = (
        f"\n\nDraft suggestion shown to the user: {suggestion['title']}. {suggestion['detail']}"
        if suggestion
        else ""
    )
    return (
        f"Group: {snapshot.name} ({snapshot.country}), month {snapshot.month}\n\n"
        + "\n\n".join(sections)
        + draft
        + (f"\n\nEarlier in this conversation:\n{history}" if history else "")
        + f"\n\nQuestion: {request.message}"
    )


def write(
    plan: Plan, reports: dict[str, AgentReport], source: str, llm: LLM | None
) -> Iterator[str]:
    if llm is None:
        yield " ".join(report.summary for report in reports.values())
        return
    yield from llm.stream(WRITER_PROMPT.format(lens=plan.lens), source)


def _figures(text: str) -> list[tuple[str, float, int]]:
    """Every figure that is not a small count: as written, its value, its decimals."""
    found = []
    for raw in FIGURE.findall(text):
        clean = raw.replace(",", "")
        decimals = len(clean.partition(".")[2])
        if decimals or float(clean) > FREE_FIGURE_MAX:
            found.append((raw, float(clean), decimals))
    return found


def untraced_figures(text: str, source: str) -> list[str]:
    """Figures in `text` that `source` does not hold, at the precision they were written with."""
    known = [float(raw.replace(",", "")) for raw in FIGURE.findall(source)]
    return [
        raw
        for raw, value, decimals in _figures(text)
        if not any(round(k, decimals) == value for k in known)
    ]


def interpret(ctx: AgentContext, report: AgentReport) -> AgentReport:
    """One bounded thought: answer the planner's ask from the tool output, and nothing beyond it.

    The answer leads the report only when every figure in it traces to that output.
    """
    if not ctx.llm or not ctx.ask or not report.findings:
        return report
    output = "\n".join([report.summary, *report.findings])
    with ctx.tool("model.think", ask=ctx.ask[:90]) as step, SerialLLM._lock:
        system = INTERPRET_PROMPT.format(label=MEMBERS[ctx.agent_id].label, ask=ctx.ask)
        try:
            answer = ctx.llm.complete(system, output).strip()
        except Exception as e:  # the figures stand without the thought
            logger.warning("Agent %s could not think: %s", ctx.agent_id, e)
            step.output = "no answer from the model, the figures stand"
            return report
        if untraced := untraced_figures(answer, output):
            step.output = f"dropped: {', '.join(untraced[:3])} not in the tool output"
            return report
        step.output = f"{len(_figures(answer))} figures, all traced to the tool output"
    return report.model_copy(
        update={"summary": answer, "findings": [report.summary, *report.findings]}
    )


def load_snapshot(
    cursor: duckdb.DuckDBPyConnection, group_id: str, month: str
) -> tuple[ScoreSnapshot | None, bool]:
    row = cursor.execute(
        """select g.name, g.country, g.sector, s.level, g.has_erp
        from scores s join groups g using (group_id)
        where s.group_id = ? and s.month = cast(? as timestamp)""",
        [group_id, month],
    ).fetchone()
    if row is None:
        return None, False
    drivers = cursor.execute(
        """select pillar, score, delta_score from drivers
        where group_id = ? and month = cast(? as timestamp)""",
        [group_id, month],
    ).fetchall()
    snapshot = ScoreSnapshot(
        group_id=group_id,
        month=month[:7],
        name=row[0],
        country=row[1],
        sector=row[2],
        level=row[3],
        pillars={pillar: score for pillar, score, _ in drivers if score is not None},
        deltas={pillar: delta for pillar, _, delta in drivers if delta is not None},
    )
    return snapshot, bool(row[4])


def scorecard(ctx: AgentContext) -> AgentReport:
    with ctx.tool("pillars_at", month=ctx.snapshot.month) as step:
        level, trend, state, tier, buffer_days, margin, ap_days, ar_days, dscr = ctx.query(
            """select level, trend, state, tier, buffer_days, operating_margin,
            ap_days_beyond_terms, ar_days_beyond_terms, dscr
            from scores where group_id = ? and month = cast(? as timestamp)"""
        )[0]
        pillars = ctx.query(
            """select pillar, score, delta_score from drivers
            where group_id = ? and month = cast(? as timestamp) and score is not null
            order by score"""
        )
        missing = [PILLAR_LABELS[p] for p in PILLAR_LABELS if p not in {r[0] for r in pillars}]
        step.output = f"level {level:.0f}, {state}, {len(pillars)} of 5 pillars"
    ctx.facts["state"] = state
    evidence = {
        "liquidity": buffer_days is not None and f"{buffer_days:.0f} days of cash buffer",
        "cash_generation": margin is not None and f"operating margin {margin:.0%}",
        "payment_discipline": ap_days is not None and f"paying {ap_days:.0f} days beyond terms",
        "collections": ar_days is not None and f"collecting {ar_days:.0f} days beyond terms",
        "debt_burden": dscr is not None and f"debt service covered {dscr:.2f}x",
    }
    findings = []
    for pillar, score, delta in pillars:
        moved = f" ({delta:+.0f} this month)" if delta else ""
        detail = f": {evidence[pillar]}" if evidence.get(pillar) else ""
        findings.append(f"{PILLAR_LABELS.get(pillar, pillar)} {score:.0f}{moved}{detail}")
    if missing:
        findings.append(f"No data for {', '.join(missing)}: the weight moved to the others.")

    with ctx.tool("drivers_window", months=DRIVER_WINDOW_MONTHS) as step:
        moves = ctx.query(
            f"""select now.pillar, now.contribution - past.contribution
            from drivers now join drivers past using (group_id, pillar)
            where now.group_id = ? and now.month = cast(? as timestamp)
              and past.month = now.month - interval {DRIVER_WINDOW_MONTHS} month
              and now.contribution is not null and past.contribution is not null
            order by 2"""
        )
        before = ctx.query(
            f"""select level from scores where group_id = ?
            and month = cast(? as timestamp) - interval {DRIVER_WINDOW_MONTHS} month"""
        )
        step.output = f"{len(moves)} pillars compared with {DRIVER_WINDOW_MONTHS} months ago"
    window = ""
    if moves and before:
        ctx.facts["worst_driver"] = moves[0][0] if moves[0][1] < 0 else None
        parts = ", ".join(f"{PILLAR_LABELS.get(p, p)} {d:+.1f}" for p, d in moves if abs(d) >= 0.5)
        window = f" It was {before[0][0]:.0f} six months earlier"
        window += f", moved by {parts}." if parts else "."

    with ctx.tool("own_history_rank") as step:
        rank, months = ctx.query(
            """select count(*) filter (where h.level > s.level) + 1, count(*)
            from scores s join scores h on h.group_id = s.group_id and h.month <= s.month
            where s.group_id = ? and s.month = cast(? as timestamp)"""
        )[0]
        step.output = f"{_ordinal(rank)} best of {months} months"

    with ctx.tool("alerts_for", until=ctx.snapshot.month) as step:
        alerts = ctx.query(
            """select month, kind, direction, state_from, state_to, onset_month, level_at_onset,
            level_at_alert, driver_1, driver_2, anticipation_months from alerts
            where group_id = ? and month <= cast(? as timestamp) order by month desc"""
        )
        step.output = f"{len(alerts)} alerts"
    fired_lines = []
    for fired, kind, direction, s_from, s_to, onset, at_onset, at_alert, d1, d2, early in alerts:
        drivers = " and ".join(PILLAR_LABELS.get(d, d) for d in (d1, d2) if d)
        what = (
            f"state changed from {s_from} to {s_to}" if s_from and s_to else f"{kind} {direction}"
        )
        since = (
            f", the move began in {onset:%Y-%m} at level {at_onset:.0f}"
            if onset and at_onset is not None
            else ""
        )
        now = f", level {at_alert:.0f} when it fired" if at_alert is not None else ""
        ahead = f", {early:.0f} months before the tier changed" if early else ""
        fired_lines.append(
            f"Alert {fired:%Y-%m}: {what}{since}{now}, "
            f"driven by {drivers or 'no single pillar'}{ahead}"
        )
    monitor = (
        f" {len(alerts)} alert{'s' if len(alerts) > 1 else ''}, the latest: {fired_lines[0]}."
        if alerts
        else " The monitor has not fired for this group."
    )
    heading = f", {trend:+.1f} points a month" if trend is not None else ""
    return AgentReport(
        agent="scorecard",
        summary=(
            f"Level {level:.0f}, {state.replace('_', ' ')}{heading}, tier {tier}.{window} "
            f"This is its {_ordinal(rank)} best month of {months}.{monitor}"
        ),
        findings=findings + fired_lines,
    )


def ledger(ctx: AgentContext) -> AgentReport:
    summary, findings = [], []
    if ctx.has_erp and any(ctx.wants(tool) for tool in INVOICE_TOOLS):
        _customers(ctx, summary, findings)
    if any(ctx.wants(tool) for tool in CASH_TOOLS):
        _cash(ctx, summary, findings)
    report = AgentReport(
        agent="ledger",
        summary=" ".join(summary) or "Nothing to read in the ledger for this group.",
        findings=findings,
    )
    return interpret(ctx, report)


def _customers(ctx: AgentContext, summary: list[str], findings: list[str]) -> None:
    with ctx.tool("concentration") as step:
        top = ctx.query(
            """select name, share_of_billing from payers
            where group_id = ? and month = cast(? as timestamp)
            order by share_of_billing desc limit 5"""
        )
        step.output = f"top 5 hold {sum(share for _, share in top):.0%} of billing"
    if not top:
        summary.append("No invoices to read for this group.")
        return
    summary.append(
        f"{top[0][0]} is {top[0][1]:.0%} of billing and the top five are "
        f"{sum(share for _, share in top):.0%}."
    )
    if ctx.wants("payer_scores"):
        with ctx.tool("payer_scores", min_paid=MIN_PAID_INVOICES) as step:
            payers = ctx.query(
                f"""select name, share_of_billing, days_late, days_late_change, payer_score
                from payers where group_id = ? and month = cast(? as timestamp) and reliable
                order by payer_score, share_of_billing desc limit {CUSTOMERS_SHOWN}"""
            )
            step.output = f"{len(payers)} customers with enough history, worst first"
        findings += [
            f"{name}: {_share(share)} of billing, pays {_days(late)} late"
            + (f" ({change:+.0f} days on the previous half year)" if change else "")
            + f", payer score {score:.0f}"
            for name, share, late, change, score in payers
            if late is not None
        ]
    if ctx.wants("overdue_ranked"):
        with ctx.tool("overdue_ranked") as step:
            overdue = ctx.query(
                f"""select name, overdue_eur, oldest_overdue_days, share_of_billing from payers
                where group_id = ? and month = cast(? as timestamp) and overdue_eur > 0
                order by overdue_eur desc limit {CUSTOMERS_SHOWN}"""
            )
            step.output = f"{len(overdue)} customers overdue"
        if overdue:
            name, amount, age, share = overdue[0]
            ctx.facts["chase"] = {
                "name": name,
                "overdue": ctx.money(amount),
                "oldest_overdue_days": age,
                "share_of_billing": share,
            }
        findings += [
            f"{name}: {ctx.money(amount)} overdue, oldest {age} days past due"
            for name, amount, age, _ in overdue
        ]
        total_overdue = sum(amount for _, amount, _, _ in overdue)
        summary.append(f"{ctx.money(total_overdue)} is overdue across {len(overdue)} customers.")


def _cash(ctx: AgentContext, summary: list[str], findings: list[str]) -> None:
    with ctx.tool("cash_profile", months=12) as step:
        margin, inflow, dscr = ctx.query(
            """select avg(h.operating_margin), s.monthly_inflow_eur, s.dscr
            from scores s join scores h on h.group_id = s.group_id
              and h.month <= s.month and h.month > s.month - interval 12 month
            where s.group_id = ? and s.month = cast(? as timestamp)
            group by all"""
        )[0]
        revenue = (inflow or 0) * 12
        cash = revenue * (margin or 0)
        step.output = f"margin {margin or 0:.0%}, free cash flow {ctx.money(cash)} a year"
    summary.append(f"Free cash flow before debt {ctx.money(cash)} a year.")
    findings.append(
        f"Revenue about {ctx.money(revenue)} a year, operating margin {margin or 0:.0%} "
        f"over twelve months, free cash flow before debt {ctx.money(cash)}."
    )
    if not ctx.wants("debt_capacity"):
        return
    with ctx.tool("debt_capacity", min_cover=MIN_COVER) as step:
        service = cash / dscr if dscr and dscr > 0 and cash > 0 else None
        headroom = max(cash / MIN_COVER - service, 0) if service is not None else None
        step.output = (
            "no positive cash flow to lever"
            if headroom is None
            else f"{ctx.money(headroom)} a year"
        )
    if headroom is not None:
        findings.append(
            f"Debt service is covered {dscr:.2f}x. At a {MIN_COVER}x floor the cash flow carries "
            f"{ctx.money(headroom)} more debt service a year."
        )


def simulator(ctx: AgentContext) -> AgentReport:
    with ctx.tool("offer_at", month=ctx.snapshot.month) as step:
        offer = ctx.query(
            """select eligible, limit_eur, apr, limit_change_eur from offers
            where group_id = ? and month = cast(? as timestamp)"""
        )
        step.output = "no offer" if not offer else f"limit {ctx.money(offer[0][1])}"
    with ctx.tool("actions_ranked") as step:
        actions = ctx.query(
            """select pillar, action, expected_level_gain from actions
            where group_id = ? and month = cast(? as timestamp) order by rank"""
        )
        step.output = f"{len(actions)} moves"
    if actions:
        pillar, action, gain = actions[0]
        ctx.facts["top_action"] = {"pillar": pillar, "action": action, "gain": gain}
    if not offer:
        summary = "No credit line priced for this month."
    elif not offer[0][0]:
        summary = "Not eligible for the working-capital line this month."
    else:
        _, limit, apr, change = offer[0]
        moved = f", {ctx.money(change, signed=True)} on last month" if change else ""
        rate = f" at {apr:.1%} APR" if apr is not None else ""
        summary = f"Working-capital line of {ctx.money(limit)}{rate}{moved}."
    findings = [
        f"{action} Expected gain {gain:+.1f} points on {PILLAR_LABELS.get(pillar, pillar)}."
        for pillar, action, gain in actions
    ]
    moves = {p: points for p, points in ctx.plan.what_if.items() if p in ctx.snapshot.pillars}
    if moves:
        findings.insert(0, _what_if(ctx, moves))
    return AgentReport(agent="simulator", summary=summary, findings=findings)


def _what_if(ctx: AgentContext, moves: dict[str, float]) -> str:
    shown = {pillar: f"{points:+.0f}" for pillar, points in moves.items()}
    with ctx.tool("what_if", **shown) as step:
        trend, inflow = ctx.query(
            """select trend, monthly_inflow_eur from scores
            where group_id = ? and month = cast(? as timestamp)"""
        )[0]
        today = ctx.snapshot.pillars
        moved = today | {p: min(max(today[p] + points, 0), 100) for p, points in moves.items()}
        level = level_of(moved)
        compound = min(max(level + TREND_MONTHS_PRICED * (trend or 0), 0), 100)
        limit = round((inflow or 0) * limit_factor(compound), -3) if compound >= MIN_COMPOUND else 0
        step.output = f"level {level_of(today):.0f} to {level:.0f}, limit {ctx.money(limit)}"
    what = ", ".join(f"{PILLAR_LABELS[p]} {points:+.0f}" for p, points in moves.items())
    return (
        f"What if {what}: the level goes from {level_of(today):.0f} to {level:.0f} and the line "
        f"would price at {ctx.money(limit)}, once the monitor's hold on the limit lifts."
    )


def level_of(pillars: dict[str, float]) -> float:
    """The engine's contract: renormalised weights over the pillars present, and the cap rule."""
    coverage = sum(PILLAR_WEIGHTS[p] for p in pillars)
    level = 50 + sum(PILLAR_WEIGHTS[p] / coverage * (score - 50) for p, score in pillars.items())
    capped = any(pillars.get(p, 100) < CAP_PILLAR_SCORE for p in CAP_PILLARS) and level > CAP_LEVEL
    return CAP_LEVEL if capped else level


def limit_factor(compound: float) -> float:
    """Months of inflow the line lends at this compound: linear between the curve's ends."""
    (low, high), (least, most) = LIMIT_CURVE
    share = min(max((compound - low) / (high - low), 0), 1)
    return least + share * (most - least)


def peers(ctx: AgentContext) -> AgentReport:
    summary, findings = [], []
    if ctx.wants("standing"):
        with ctx.tool("standing", month=ctx.snapshot.month) as step:
            by_level, by_trend, scored = ctx.query(
                """select count(*) filter (where o.level > s.level) + 1,
                    count(*) filter (where o.trend > s.trend) + 1, count(*)
                from scores s join scores o on o.month = s.month
                where s.group_id = ? and s.month = cast(? as timestamp)"""
            )[0]
            step.output = f"{_ordinal(by_level)} of {scored} by level"
        summary.append(
            f"{_ordinal(by_level)} of {scored} groups by level and {_ordinal(by_trend)} by trend."
        )
    if ctx.plan.compare and ctx.wants("compare"):
        findings += _compare(ctx, ctx.plan.compare, summary)
    if ctx.plan.lens == "investor" and ctx.wants("screen"):
        findings.append(_screen(ctx, summary))
    if ctx.wants("comparables"):
        with ctx.tool("comparables", country=ctx.snapshot.country) as step:
            similar = ctx.query(
                """select count(*) from groups g,
                    (select annual_revenue_eur r, country c from groups where group_id = $1) me
                where g.group_id <> $1 and g.country is not distinct from me.c
                  and g.annual_revenue_eur between me.r / 3 and me.r * 3""",
                [ctx.request.group_id],
            )[0][0]
            step.output = f"{similar} groups within a third to three times its size"
        findings.append(
            f"{similar} comparable groups by size in {ctx.snapshot.country or 'its country'}. "
            "No sector in the data, so whether they are the same business is unknown."
        )
    report = AgentReport(agent="peers", summary=" ".join(summary), findings=findings)
    return interpret(ctx, report)


def _compare(ctx: AgentContext, other: str, summary: list[str]) -> list[str]:
    with ctx.tool("compare", group=other) as step:
        level, trend, state = ctx.query(
            """select level, trend, state from scores
            where group_id = ? and month = cast(? as timestamp)""",
            [other, ctx.request.month],
        )[0]
        theirs = dict(
            ctx.query(
                """select pillar, score from drivers where group_id = ?
                and month = cast(? as timestamp) and score is not null""",
                [other, ctx.request.month],
            )
        )
        step.output = f"{other} level {level:.0f}, {state}"
    # Adding zero turns a rounded -0.0 into 0.0.
    heading = f", {round(trend, 1) + 0.0:+.1f} points a month" if trend is not None else ""
    summary.append(
        f"{other} is at level {level:.0f}, {state.replace('_', ' ')}{heading}, "
        f"against {ctx.snapshot.level:.0f} here."
    )
    return [
        f"{PILLAR_LABELS[p]}: {ctx.snapshot.pillars[p]:.0f} here, {theirs[p]:.0f} at {other}"
        for p in PILLAR_LABELS
        if p in theirs and p in ctx.snapshot.pillars
    ]


def _screen(ctx: AgentContext, summary: list[str]) -> str:
    with ctx.tool("screen", lens="search fund") as step:
        margin, steadiness, level, state, n_companies = ctx.query(
            """select avg(h.operating_margin), stddev(h.operating_margin), s.level, s.state,
                g.n_companies
            from scores s join groups g using (group_id)
            join scores h on h.group_id = s.group_id
              and h.month <= s.month and h.month > s.month - interval 12 month
            where s.group_id = ? and s.month = cast(? as timestamp)
            group by all"""
        )[0]
        tests = {
            "one company": n_companies == 1,
            f"margin {SEARCH_FUND_MARGIN:.0%} or more": (margin or 0) >= SEARCH_FUND_MARGIN,
            "margin steady for a year": steadiness is not None and steadiness < MARGIN_STEADY,
            f"level {SEARCH_FUND_LEVEL} or higher": level >= SEARCH_FUND_LEVEL,
            "not bending or falling": state not in ("bending", "falling"),
        }
        scored, passing = ctx.query(
            f"""with m as (select group_id, avg(operating_margin) mu, stddev(operating_margin) sd
                from scores where month <= cast($1 as timestamp)
                  and month > cast($1 as timestamp) - interval 12 month group by 1)
            select count(*), count(*) filter (where g.n_companies = 1
                and mu >= {SEARCH_FUND_MARGIN} and sd < {MARGIN_STEADY}
                and s.level >= {SEARCH_FUND_LEVEL} and s.state not in ('bending', 'falling'))
            from m join groups g using (group_id)
            join scores s on s.group_id = m.group_id and s.month = cast($1 as timestamp)""",
            [ctx.request.month],
        )[0]
        failed = [name for name, ok in tests.items() if not ok]
        step.output = (
            f"{len(tests) - len(failed)} of {len(tests)} tests, "
            f"{passing} of {scored} groups pass them all"
        )
    fit = "passes the search fund screen" if not failed else f"fails it on: {', '.join(failed)}"
    summary.append(f"As a target it {fit}.")
    return f"Search fund screen: {fit}. {passing} of {scored} groups in the portfolio pass."


def _context_cache(ctx: AgentContext) -> JsonCache:
    ttl = timedelta(days=ctx.settings.context_ttl_days)
    return JsonCache(ctx.settings.serving_dir / "context", ttl)


def _read(ctx: AgentContext, agent: Any, snapshot: ScoreSnapshot) -> AgentReport:
    """Run one public-context agent with its searches traced, and say so when the cache answered."""
    tool_name = "tavily.search" if agent.name == "context_retrieval" else "exa.search"
    search = agent.search

    def traced(query: str, *args: Any, **kwargs: Any):
        with ctx.tool(tool_name, query=query[:90]) as step:
            result = search(query, *args, **kwargs)
            step.output = f"{len(getattr(result, 'results', result))} pages"
            return result

    agent.search = traced
    steps_before = ctx.steps
    report = agent.run(snapshot)
    if ctx.steps == steps_before and report.findings:
        with ctx.tool("cache.read", report=agent.name) as step:
            step.output = "read younger than a week: no search, no tokens"
    return report


def macro(ctx: AgentContext) -> AgentReport:
    """The read of the country. Keyed by country, so every group there shares one read."""
    llm = SerialLLM(ctx.llm, ctx) if ctx.llm else None
    report = _read(
        ctx, SectorAgent(ctx.settings.exa_api_key, llm, _context_cache(ctx)), ctx.snapshot
    )
    return report.model_copy(update={"agent": "macro"})


def market(ctx: AgentContext) -> AgentReport:
    """Peers and press of the real company the user named."""
    llm = SerialLLM(ctx.llm, ctx) if ctx.llm else None
    cache = _context_cache(ctx)
    named = ctx.snapshot.model_copy(update={"name": ctx.plan.company})
    parts = [
        _read(ctx, PeersAgent(ctx.settings.exa_api_key, llm, cache), named),
        _read(ctx, ContextRetrievalAgent(ctx.settings.tavily_api_key, llm, cache), named),
    ]
    return AgentReport(
        agent="market",
        summary=" ".join(part.summary for part in parts),
        findings=[finding for part in parts for finding in part.findings],
        sources=sorted({source for part in parts for source in part.sources}),
    )


AGENTS: dict[str, Callable[[AgentContext], AgentReport]] = {
    "scorecard": scorecard,
    "ledger": ledger,
    "simulator": simulator,
    "peers": peers,
    "macro": macro,
    "market": market,
}


def _timed(
    run: Callable[[AgentContext], AgentReport], ctx: AgentContext
) -> tuple[AgentReport, int]:
    t0 = time.monotonic()
    return run(ctx), _ms(t0)


def _outcome(agent_id: str, future: Future, reports: dict[str, AgentReport]) -> dict:
    try:
        report, ms = future.result()
    except Exception as e:  # one agent failing must not cost the answer
        logger.warning("Agent %s failed: %s", agent_id, e)
        return {"type": "agent", "id": agent_id, "status": "failed", "error": str(e)[:200]}
    reports[agent_id] = report
    return {
        "type": "agent",
        "id": agent_id,
        "status": "done",
        "summary": report.summary,
        "findings": report.findings,
        "sources": report.sources,
        "ms": ms,
    }


def _drain(events: "queue.Queue[dict]") -> Iterator[dict]:
    while True:
        try:
            yield events.get_nowait()
        except queue.Empty:
            return


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


@lru_cache
def _usd_per_eur() -> dict[int, float]:
    rates_file = Path(__file__).parents[1] / "pipeline" / "fx_rates.csv"
    with rates_file.open() as handle:
        return {
            int(row["year"]): float(row["per_eur"])
            for row in csv.DictReader(handle)
            if row["currency"] == "USD"
        }


def display_rate(currency: str, year: int) -> float:
    """Units of the display currency per euro at the average rate of `year`."""
    if currency == "EUR":
        return 1.0
    rates = _usd_per_eur()
    return rates[min(rates, key=lambda known: abs(known - year))]


def _share(share: float) -> str:
    return "under 1%" if share < 0.01 else f"{share:.0%}"


def _days(days: float) -> str:
    return f"{days:.0f} day{'' if round(days) == 1 else 's'}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

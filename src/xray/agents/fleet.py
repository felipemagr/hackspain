"""The chat: a planner directs a small fleet over one group and month, a writer answers.

Every agent is a purpose, a set of rules and a set of tools. The rules are code and are shown on
screen. Each tool call is an event, so the screen can show what every agent is doing while it
does it. No number comes from the model: it routes and it writes, SQL produces the figures.

`run_chat` yields plain dict events: planning, plan, agent, step, dispatch, suggestion, writing,
token, done. Agents run in threads and report through one queue. Searches run in parallel but
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

Purpose = Literal["diagnose", "anticipate", "collect", "finance", "market", "invest"]


class Tool(BaseModel):
    name: str
    does: str


class FleetMember(BaseModel):
    id: str
    label: str
    purpose: str
    rules: list[str]
    tools: list[Tool]


ROSTER: tuple[FleetMember, ...] = (
    FleetMember(
        id="diagnosis",
        label="Diagnosis",
        purpose="Why the score moved.",
        rules=[
            "Every figure is read from the score tables, never produced by the model.",
            "A pillar the group has no data for is declared, not imputed.",
            "A level is judged against the group's own history, not only the 0-100 scale.",
        ],
        tools=[
            Tool(name="pillars_at", does="level, state, trend and the five pillars this month"),
            Tool(name="drivers_window", does="which pillars moved the level over six months"),
            Tool(name="own_history_rank", does="where this level sits in the group's own months"),
        ],
    ),
    FleetMember(
        id="monitor",
        label="Monitor",
        purpose="What was flagged, and how early.",
        rules=[
            "One bad month is a bump: it never triggers a limit review on its own.",
            "Anticipation is measured against the month the tier actually changed.",
        ],
        tools=[Tool(name="alerts_for", does="alerts fired up to this month, with their drivers")],
    ),
    FleetMember(
        id="working_capital",
        label="Working capital",
        purpose="The credit line, and what raises it.",
        rules=[
            "The limit is priced on level plus four months of trend.",
            "Anything that moves money leaves as a draft for a person to sign.",
        ],
        tools=[
            Tool(name="offer_at", does="limit, price and change on last month"),
            Tool(name="actions_ranked", does="next moves ranked by expected gain in points"),
        ],
    ),
    FleetMember(
        id="customers",
        label="Customers",
        purpose="Who pays late, and how much rides on them.",
        rules=[
            f"A customer needs {MIN_PAID_INVOICES} paid invoices before its lateness counts.",
            "A customer is judged only on how it paid this group: ids do not link across groups.",
            "Open and overdue are rebuilt as of the month, never read from the final snapshot.",
            "Amounts are in euros at the average rate of the year each invoice was issued.",
        ],
        tools=[
            Tool(name="concentration", does="share of billing on the largest customers"),
            Tool(name="payer_scores", does="days late, its change and a 0-100 score per customer"),
            Tool(name="overdue_ranked", does="who to chase first: overdue amount and its age"),
        ],
    ),
    FleetMember(
        id="investor",
        label="Investor",
        purpose="How a buyer would see the group.",
        rules=[
            "Free cash flow is taken before debt service: what an enterprise value discounts.",
            f"Search fund fit: one company, operating margin of {SEARCH_FUND_MARGIN:.0%} or "
            f"more, steady for a year, level {SEARCH_FUND_LEVEL} or higher, not bending or falling.",  # noqa: E501
            f"Debt capacity keeps debt service covered {MIN_COVER}x by operating cash.",
            "The data has no sector and no valuation multiples: no enterprise value is estimated, "
            "and roll-up comparables are by country and size only.",
        ],
        tools=[
            Tool(name="cash_profile", does="margin, its steadiness and free cash flow before debt"),
            Tool(name="debt_capacity", does="extra debt service the cash flow could carry"),
            Tool(name="screen", does="the search fund test, and how many groups pass it"),
            Tool(name="comparables", does="groups of similar size in the country, for a roll-up"),
        ],
    ),
    FleetMember(
        id="market",
        label="Market",
        purpose="Is it us, or the market.",
        rules=[
            "Only dated facts with a source.",
            "Competitors are read only for a real company the user names.",
        ],
        tools=[
            Tool(name="exa.search", does="recent news on the sector or the country"),
            Tool(name="tavily.search", does="press and registry on a named company"),
            Tool(name="model.read", does="extracts dated facts from the pages found"),
        ],
    ),
)
MEMBERS = {member.id: member for member in ROSTER}

PLANNER_PROMPT = """You direct a fleet of agents inside a financial health monitor used by a CFO.
Classify the question and dispatch only the agents the answer needs. `diagnosis` always runs.

Purposes: diagnose (why the score moved), anticipate (when it was visible, bump or fall),
collect (customers, late payers, who to chase), finance (credit line, what to do, next moves),
market (is it us or the market), invest (is this a company worth buying, search fund, roll-up,
leverage, free cash flow).

Agents:
{roster}

The group has invoice data: {has_erp}. Without it `customers` has nothing to read.
Groups are anonymous ids. Set `company` only when the user names a real-world company.
Set `wants_action` when the user asks what to do, who to chase or what to change.

Answer with JSON only:
{{"purpose": "diagnose", "agents": ["diagnosis"], "company": null, "wants_action": false,
"reasons": {{"diagnosis": "up to eight words on why"}}}}"""

WRITER_PROMPT = """You are X Ray, the analyst inside a financial health monitor used by a CFO.
Answer the question using only the agent reports below. Lead with the answer in one sentence.
Then the evidence: which pillar moved, since when, with the numbers from the reports. When the
question is about what to do, end with the ranked moves. Say plainly when the reports do not
hold the answer. Never invent a number.

States: a bump is one bad month that recovers; bending is a sustained early decline while the
level still looks fine; falling is structural decline; improving is a sustained rise. The
current state is the one Diagnosis reports. A draft suggestion, when present, is shown to the
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
PURPOSE_RULES: tuple[tuple[Purpose, str, list[str]], ...] = (
    ("invest", r"invest|buy|acqui|search fund|roll.?up|leverage|comprar|inver", ["investor"]),
    ("collect", r"customer|client|pay(s|ing)? (me|us)|late|chase|cobr|moros", ["customers"]),
    ("finance", r"credit|line|limit|financ|anticip|circulante|do this week", ["working_capital"]),
    ("market", r"sector|market|compet|peer|mercado", ["market"]),
    ("anticipate", r"bump|fall|visible|early|alert|bache|ca[ií]da|antes", ["monitor"]),
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
    purpose: Purpose = "diagnose"
    agents: list[str]
    company: str | None = None
    wants_action: bool = False
    reasons: dict[str, str] = Field(default_factory=dict)


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
    company: str | None
    emit: Callable[[dict], None]
    facts: dict[str, Any] = field(default_factory=dict)
    steps: int = 0

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
    """Plan, dispatch, follow up once, suggest, write."""
    started = time.monotonic()
    snapshot, has_erp = load_snapshot(db.cursor(), request.group_id, request.month)
    if snapshot is None:
        yield {"type": "error", "message": "No score for that group and month."}
        return
    llm = build_llm(settings, reasoning_effort="low")

    yield {"type": "planning"}
    plan = make_plan(request, snapshot, has_erp, llm)
    yield {
        "type": "plan",
        "purpose": plan.purpose,
        "company": plan.company,
        "agents": [{"id": a, "reason": plan.reasons.get(a, "")} for a in plan.agents],
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
                    agent_id, request, snapshot, db.cursor(), settings, llm, plan.company,
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
    try:
        for text in write(request, snapshot, reports, suggestion, llm):
            yield {"type": "token", "text": text}
    except Exception as e:  # the trace above already holds the evidence
        logger.warning("Writer failed: %s", e)
        yield {"type": "error", "message": "The writer could not finish. The agent reports stand."}
    yield {"type": "done", "ms": _ms(started)}


def make_plan(
    request: ChatRequest, snapshot: ScoreSnapshot, has_erp: bool, llm: LLM | None
) -> Plan:
    """Ask the model to classify and dispatch. Without it, or if it fails, use rules."""
    plan = None
    if llm:
        roster = "\n".join(f"- {member.id}: {member.purpose}" for member in ROSTER)
        system = PLANNER_PROMPT.format(roster=roster, has_erp="yes" if has_erp else "no")
        user = f"Group: {snapshot.name} ({snapshot.country})\nQuestion: {request.message}"
        try:
            plan = complete_json(llm, system, user, Plan)
        except Exception as e:  # a bad plan must not cost the answer
            logger.warning("Planner failed, using rules: %s", e)
    if plan is None:
        plan = Plan(agents=["diagnosis", "monitor"])
        for purpose, pattern, agents in PURPOSE_RULES:
            if re.search(pattern, request.message, re.I):
                plan = Plan(purpose=purpose, agents=["diagnosis", *agents])
                break
        plan.wants_action = bool(ACTION_WORDS.search(request.message))
    wanted = dict.fromkeys(["diagnosis", *plan.agents])
    known = [a for a in wanted if a in MEMBERS and (has_erp or a != "customers")]
    return plan.model_copy(update={"agents": sorted(known, key=list(MEMBERS).index)})


def director_follow_up(
    plan: Plan, reports: dict[str, AgentReport], facts: dict[str, Any], has_erp: bool
) -> list[dict]:
    """One extra dispatch, decided by rules on what Diagnosis found. At most once per question."""
    if facts.get("followed_up") or "diagnosis" not in reports:
        return []
    facts["followed_up"] = True
    extra = []
    if facts.get("worst_driver") == "collections" and has_erp and "customers" not in plan.agents:
        extra.append(
            {"id": "customers", "reason": "collections is dragging the level: who pays late?"}
        )
    if facts.get("state") in ("bending", "falling") and "monitor" not in plan.agents:
        extra.append({"id": "monitor", "reason": f"state is {facts['state']}: when did it start?"})
    return extra


def draft_suggestion(plan: Plan, facts: dict[str, Any]) -> dict | None:
    """The one action to put in front of a person. Built from figures, never from the model."""
    if not plan.wants_action:
        return None
    if chase := facts.get("chase"):
        return {
            "agent": "customers",
            "title": f"Chase {chase['name']} this week",
            "detail": (
                f"{chase['overdue']} overdue, the oldest invoice "
                f"{chase['oldest_overdue_days']} days past due. It is "
                f"{chase['share_of_billing']:.0%} of the last twelve months of billing."
            ),
        }
    if action := facts.get("top_action"):
        return {
            "agent": "working_capital",
            "title": f"Act on {PILLAR_LABELS.get(action['pillar'], action['pillar'])}",
            "detail": f"{action['action']} Expected gain {action['gain']:+.1f} points.",
        }
    return None


def write(
    request: ChatRequest,
    snapshot: ScoreSnapshot,
    reports: dict[str, AgentReport],
    suggestion: dict | None,
    llm: LLM | None,
) -> Iterator[str]:
    if llm is None:
        yield " ".join(report.summary for report in reports.values())
        return
    sections = [
        f"## {MEMBERS[agent_id].label}\n{report.summary}\n" + "\n".join(report.findings)
        for agent_id, report in reports.items()
    ]
    history = "\n".join(f"{turn.role}: {turn.content}" for turn in request.history)
    draft = f"\n\nDraft suggestion shown to the user: {suggestion['title']}." if suggestion else ""
    user = (
        f"Group: {snapshot.name} ({snapshot.country}), month {snapshot.month}\n\n"
        + "\n\n".join(sections)
        + draft
        + (f"\n\nEarlier in this conversation:\n{history}" if history else "")
        + f"\n\nQuestion: {request.message}"
    )
    yield from llm.stream(WRITER_PROMPT, user)


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


def diagnosis(ctx: AgentContext) -> AgentReport:
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
    heading = f", {trend:+.1f} points a month" if trend is not None else ""
    return AgentReport(
        agent="diagnosis",
        summary=(
            f"Level {level:.0f}, {state.replace('_', ' ')}{heading}, tier {tier}.{window} "
            f"This is its {_ordinal(rank)} best month of {months}."
        ),
        findings=findings,
    )


def monitor(ctx: AgentContext) -> AgentReport:
    with ctx.tool("alerts_for", until=ctx.snapshot.month) as step:
        alerts = ctx.query(
            """select month, kind, direction, state_from, state_to, onset_month, level_at_onset,
            level_at_alert, driver_1, driver_2, anticipation_months from alerts
            where group_id = ? and month <= cast(? as timestamp) order by month desc"""
        )
        step.output = f"{len(alerts)} alerts"
    if not alerts:
        return AgentReport(agent="monitor", summary="The monitor has not fired for this group.")
    findings = []
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
        findings.append(
            f"{fired:%Y-%m}: {what}{since}{now}, driven by {drivers or 'no single pillar'}{ahead}"
        )
    return AgentReport(
        agent="monitor",
        summary=f"{len(alerts)} alert{'s' if len(alerts) > 1 else ''}, the latest: {findings[0]}.",
        findings=findings,
    )


def working_capital(ctx: AgentContext) -> AgentReport:
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
    return AgentReport(
        agent="working_capital",
        summary=summary,
        findings=[
            f"{action} Expected gain {gain:+.1f} points on {PILLAR_LABELS.get(pillar, pillar)}."
            for pillar, action, gain in actions
        ],
    )


def customers(ctx: AgentContext) -> AgentReport:
    with ctx.tool("concentration") as step:
        top = ctx.query(
            """select name, share_of_billing from payers
            where group_id = ? and month = cast(? as timestamp)
            order by share_of_billing desc limit 5"""
        )
        step.output = f"top 5 hold {sum(share for _, share in top):.0%} of billing"
    if not top:
        return AgentReport(agent="customers", summary="No invoices to read for this group.")
    with ctx.tool("payer_scores", min_paid=MIN_PAID_INVOICES) as step:
        payers = ctx.query(
            f"""select name, share_of_billing, days_late, days_late_change, payer_score
            from payers where group_id = ? and month = cast(? as timestamp) and reliable
            order by payer_score, share_of_billing desc limit {CUSTOMERS_SHOWN}"""
        )
        step.output = f"{len(payers)} customers with enough history, worst first"
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
    findings = [
        f"{name}: {_share(share)} of billing, pays {_days(late)} late"
        + (f" ({change:+.0f} days on the previous half year)" if change else "")
        + f", payer score {score:.0f}"
        for name, share, late, change, score in payers
        if late is not None
    ]
    findings += [
        f"{name}: {ctx.money(amount)} overdue, oldest {age} days past due"
        for name, amount, age, _ in overdue
    ]
    total_overdue = sum(amount for _, amount, _, _ in overdue)
    return AgentReport(
        agent="customers",
        summary=(
            f"{top[0][0]} is {top[0][1]:.0%} of billing and the top five are "
            f"{sum(share for _, share in top):.0%}. {ctx.money(total_overdue)} is overdue across "
            f"{len(overdue)} customers."
        ),
        findings=findings,
    )


def investor(ctx: AgentContext) -> AgentReport:
    with ctx.tool("cash_profile", months=12) as step:
        margin, steadiness, inflow, dscr, level, state, n_companies, country = ctx.query(
            """select avg(h.operating_margin), stddev(h.operating_margin), s.monthly_inflow_eur,
            s.dscr, s.level, s.state, g.n_companies, g.country
            from scores s join groups g using (group_id)
            join scores h on h.group_id = s.group_id
              and h.month <= s.month and h.month > s.month - interval 12 month
            where s.group_id = ? and s.month = cast(? as timestamp)
            group by all"""
        )[0]
        revenue = (inflow or 0) * 12
        cash = revenue * (margin or 0)
        step.output = f"margin {margin or 0:.0%}, free cash flow {ctx.money(cash)} a year"
    with ctx.tool("debt_capacity", min_cover=MIN_COVER) as step:
        service = cash / dscr if dscr and dscr > 0 and cash > 0 else None
        headroom = max(cash / MIN_COVER - service, 0) if service is not None else None
        step.output = (
            "no positive cash flow to lever"
            if headroom is None
            else f"{ctx.money(headroom)} a year"
        )
    with ctx.tool("screen") as step:
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
    with ctx.tool("comparables", country=country) as step:
        peers = ctx.query(
            """select count(*) from groups g,
                (select annual_revenue_eur r, country c from groups where group_id = $1) me
            where g.group_id <> $1 and g.country is not distinct from me.c
              and g.annual_revenue_eur between me.r / 3 and me.r * 3""",
            [ctx.request.group_id],
        )[0][0]
        step.output = f"{peers} groups within a third to three times its size"
    fit = "passes the search fund screen" if not failed else f"fails it on: {', '.join(failed)}"
    findings = [
        f"Revenue about {ctx.money(revenue)} a year, operating margin {margin or 0:.0%} "
        f"over twelve months, free cash flow before debt {ctx.money(cash)}.",
        f"Search fund screen: {fit}. {passing} of {scored} groups in the portfolio pass.",
        f"Roll-up: {peers} comparable groups by size in {country or 'its country'}. "
        "No sector in the data, so whether they are the same business is unknown.",
    ]
    if headroom is not None:
        findings.insert(
            1,
            f"Debt service is covered {dscr:.2f}x. At a {MIN_COVER}x floor the cash flow carries "
            f"{ctx.money(headroom)} more debt service a year.",
        )
    return AgentReport(
        agent="investor",
        summary=f"As a target it {fit}. Free cash flow before debt {ctx.money(cash)} a year.",
        findings=findings,
    )


def market(ctx: AgentContext) -> AgentReport:
    """The market read for any group, plus peers and press when the user named a real company."""
    llm = SerialLLM(ctx.llm, ctx) if ctx.llm else None
    ttl = timedelta(days=ctx.settings.context_ttl_days)
    cache = JsonCache(ctx.settings.serving_dir / "context", ttl)

    def traced(name: str, search: Callable) -> Callable:
        def run(query: str, *args: Any, **kwargs: Any):
            with ctx.tool(name, query=query[:90]) as step:
                result = search(query, *args, **kwargs)
                step.output = f"{len(getattr(result, 'results', result))} pages"
                return result

        return run

    runs: list[tuple[Any, ScoreSnapshot]] = [
        (SectorAgent(ctx.settings.exa_api_key, llm, cache), ctx.snapshot)
    ]
    if ctx.company:
        named = ctx.snapshot.model_copy(update={"name": ctx.company})
        runs.append((PeersAgent(ctx.settings.exa_api_key, llm, cache), named))
        runs.append((ContextRetrievalAgent(ctx.settings.tavily_api_key, llm, cache), named))
    parts = []
    for agent, snapshot in runs:
        tool_name = "tavily.search" if agent.name == "context_retrieval" else "exa.search"
        agent.search = traced(tool_name, agent.search)
        steps_before = ctx.steps
        report = agent.run(snapshot)
        if ctx.steps == steps_before and report.findings:
            with ctx.tool("cache.read", report=agent.name) as step:
                step.output = "report younger than a week, no search needed"
        parts.append(report)
    return AgentReport(
        agent="market",
        summary=" ".join(part.summary for part in parts),
        findings=[finding for part in parts for finding in part.findings],
        sources=sorted({source for part in parts for source in part.sources}),
    )


AGENTS: dict[str, Callable[[AgentContext], AgentReport]] = {
    "diagnosis": diagnosis,
    "monitor": monitor,
    "working_capital": working_capital,
    "customers": customers,
    "investor": investor,
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

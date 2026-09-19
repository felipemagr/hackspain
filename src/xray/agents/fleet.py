"""The chat: a planner picks agents, they run over one group and month, a writer answers.

`run_chat` yields plain dict events as things happen, so the API can stream them and the screen
can show the fleet at work. Data agents read the serving tables and are instant. Web agents
search in parallel, but their model calls go one at a time: Helmcode stalls concurrent requests
on one key.
"""

import logging
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from typing import Literal

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
# Faster than any network round trip: the report came from the cache.
CACHED_BELOW_SECONDS = 0.15


class FleetMember(BaseModel):
    id: str
    label: str
    reads: str
    kind: Literal["data", "web"]


ROSTER: tuple[FleetMember, ...] = (
    FleetMember(
        id="score", label="Score analyst", reads="level, trend and the five pillars", kind="data"
    ),
    FleetMember(
        id="monitor", label="Monitor", reads="alerts and how early they fired", kind="data"
    ),
    FleetMember(
        id="credit", label="Credit desk", reads="the credit line and the next moves", kind="data"
    ),
    FleetMember(id="sector", label="Sector scout", reads="sector news for the country", kind="web"),
    FleetMember(id="context", label="Public context", reads="press and registry", kind="web"),
    FleetMember(id="peers", label="Peers", reads="competitors and their news", kind="web"),
)
MEMBERS = {member.id: member for member in ROSTER}

PLANNER_PROMPT = """You route a CFO's question to a fleet of agents inside a financial health
monitor. Pick only the agents whose output the answer needs. `score` is always included.

Agents:
{roster}

Most groups in this portfolio are fictional demo names. Pick `context` or `peers` only when the
group is a real-world company you know, or when the user names one, and put it in `company`.
`sector` works for any group.

Answer with JSON only:
{{"agents": ["score"], "company": null, "reasons": {{"score": "up to eight words on why"}}}}"""

WRITER_PROMPT = """You are X Ray, the analyst inside a financial health monitor used by a CFO.
Answer the question using only the agent reports below. Lead with the answer in one sentence.
Then the evidence: which pillar moved, since when, with the numbers from the reports. When the
question is about what to do, end with the ranked moves. Say plainly when the reports do not
hold the answer. Never invent a number.

States: a bump is one bad month that recovers; bending is a sustained early decline while the
level still looks fine; falling is structural decline; improving is a sustained rise. The
current state is the one the score analyst reports.

Plain text, short paragraphs, no markdown, no bullets, no headings. At most 150 words.
Answer in the language of the question."""

PILLAR_LABELS = {
    "liquidity": "liquidity",
    "cash_generation": "cash generation",
    "payment_discipline": "payment discipline",
    "collections": "collections",
    "debt_burden": "debt burden",
}


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """One question about one group at one month, with the recent turns for follow-ups."""

    message: str
    group_id: str
    month: str
    history: list[ChatTurn] = Field(default_factory=list)

    @field_validator("message", mode="before")
    @classmethod
    def _trim(cls, value: str) -> str:
        return str(value).strip()[:MAX_MESSAGE_CHARS]

    @field_validator("history", mode="after")
    @classmethod
    def _recent(cls, value: list[ChatTurn]) -> list[ChatTurn]:
        return value[-MAX_HISTORY_TURNS:]


class Plan(BaseModel):
    agents: list[str]
    company: str | None = None
    reasons: dict[str, str] = Field(default_factory=dict)


class SerialLLM:
    """One model call at a time across threads."""

    _lock = threading.Lock()

    def __init__(self, llm: LLM):
        self.llm = llm

    def complete(self, system: str, user: str) -> str:
        with self._lock:
            return self.llm.complete(system, user)


def run_chat(
    request: ChatRequest, db: duckdb.DuckDBPyConnection, settings: Settings
) -> Iterator[dict]:
    """Plan, run the agents, write the answer. Yields events: planning, plan, agent, token, done."""
    started = time.monotonic()
    cursor = db.cursor()
    snapshot = load_snapshot(cursor, request.group_id, request.month)
    if snapshot is None:
        yield {"type": "error", "message": "No score for that group and month."}
        return
    llm = build_llm(settings, reasoning_effort="low")

    yield {"type": "planning"}
    plan = make_plan(request, snapshot, llm)
    yield {
        "type": "plan",
        "company": plan.company,
        "agents": [
            MEMBERS[agent_id].model_dump() | {"reason": plan.reasons.get(agent_id, "")}
            for agent_id in plan.agents
        ],
    }

    reports: dict[str, AgentReport] = {}
    for agent_id in (a for a in plan.agents if MEMBERS[a].kind == "data"):
        yield {"type": "agent", "id": agent_id, "status": "running"}
        t0 = time.monotonic()
        reports[agent_id] = DATA_AGENTS[agent_id](cursor, request.group_id, request.month)
        yield _finished(agent_id, reports[agent_id], t0, cached=False)

    web = [a for a in plan.agents if MEMBERS[a].kind == "web"]
    if web:
        agents = build_web_agents(settings, llm)
        # Context and peers read a real company; the sector scout reads the group itself.
        named = snapshot.model_copy(update={"name": plan.company or snapshot.name})
        with ThreadPoolExecutor(max_workers=len(web)) as pool:
            futures = {}
            for agent_id in web:
                yield {"type": "agent", "id": agent_id, "status": "running"}
                target = snapshot if agent_id == "sector" else named
                futures[pool.submit(_timed, agents[agent_id].run, target)] = agent_id
            for future in as_completed(futures):
                agent_id = futures[future]
                try:
                    report, seconds = future.result()
                except Exception as e:  # one agent failing must not cost the answer
                    logger.warning("Agent %s failed: %s", agent_id, e)
                    yield {
                        "type": "agent",
                        "id": agent_id,
                        "status": "failed",
                        "error": str(e)[:200],
                    }
                    continue
                reports[agent_id] = report
                yield _finished(
                    agent_id, report, time.monotonic() - seconds, seconds < CACHED_BELOW_SECONDS
                )

    yield {"type": "writing"}
    try:
        yield from (
            {"type": "token", "text": text} for text in write(request, snapshot, reports, llm)
        )
    except Exception as e:  # the trace above already holds the evidence
        logger.warning("Writer failed: %s", e)
        yield {"type": "error", "message": "The writer could not finish. The agent reports stand."}
    yield {"type": "done", "ms": round((time.monotonic() - started) * 1000)}


def make_plan(request: ChatRequest, snapshot: ScoreSnapshot, llm: LLM | None) -> Plan:
    """Ask the model which agents the question needs. Without it, or if it fails, use rules."""
    plan = None
    if llm:
        roster = "\n".join(f"- {member.id}: {member.reads}" for member in ROSTER)
        user = (
            f"Group: {snapshot.name} ({snapshot.sector}, {snapshot.country})\n"
            f"Question: {request.message}"
        )
        try:
            plan = complete_json(llm, PLANNER_PROMPT.format(roster=roster), user, Plan)
        except Exception as e:  # a bad plan must not cost the answer
            logger.warning("Planner failed, using rules: %s", e)
    if plan is None:
        words = request.message.lower()
        outside = any(word in words for word in ("sector", "market", "peer", "compet", "mercado"))
        plan = Plan(agents=["score", "monitor", "credit", *(["sector"] if outside else [])])
    known = [a for a in dict.fromkeys(["score", *plan.agents]) if a in MEMBERS]
    return plan.model_copy(update={"agents": sorted(known, key=list(MEMBERS).index)})


def build_web_agents(settings: Settings, llm: LLM | None) -> dict:
    serial = SerialLLM(llm) if llm else None
    cache = JsonCache(settings.serving_dir / "context", timedelta(days=settings.context_ttl_days))
    return {
        "context": ContextRetrievalAgent(settings.tavily_api_key, serial, cache),
        "peers": PeersAgent(settings.exa_api_key, serial, cache),
        "sector": SectorAgent(settings.exa_api_key, serial, cache),
    }


def write(
    request: ChatRequest, snapshot: ScoreSnapshot, reports: dict[str, AgentReport], llm: LLM | None
) -> Iterator[str]:
    if llm is None:
        yield " ".join(report.summary for report in reports.values())
        return
    sections = [
        f"## {MEMBERS[agent_id].label}\n{report.summary}\n" + "\n".join(report.findings)
        for agent_id, report in reports.items()
    ]
    history = "\n".join(f"{turn.role}: {turn.content}" for turn in request.history)
    user = (
        f"Group: {snapshot.name} ({snapshot.sector}, {snapshot.country}), "
        f"month {snapshot.month}\n\n"
        + "\n\n".join(sections)
        + (f"\n\nEarlier in this conversation:\n{history}" if history else "")
        + f"\n\nQuestion: {request.message}"
    )
    yield from llm.stream(WRITER_PROMPT, user)


def load_snapshot(
    cursor: duckdb.DuckDBPyConnection, group_id: str, month: str
) -> ScoreSnapshot | None:
    row = cursor.execute(
        """select g.name, g.country, g.sector, s.level from scores s join groups g using (group_id)
        where s.group_id = ? and s.month = cast(? as timestamp)""",
        [group_id, month],
    ).fetchone()
    if row is None:
        return None
    drivers = cursor.execute(
        """select pillar, score, delta_score from drivers
        where group_id = ? and month = cast(? as timestamp)""",
        [group_id, month],
    ).fetchall()
    return ScoreSnapshot(
        group_id=group_id,
        month=month[:7],
        name=row[0],
        country=row[1],
        sector=row[2],
        level=row[3],
        pillars={pillar: score for pillar, score, _ in drivers if score is not None},
        deltas={pillar: delta for pillar, _, delta in drivers if delta is not None},
    )


def score_report(cursor: duckdb.DuckDBPyConnection, group_id: str, month: str) -> AgentReport:
    level, trend, state, tier, buffer_days, margin, ap_days, ar_days, dscr = cursor.execute(
        """select level, trend, state, tier, buffer_days, operating_margin,
        ap_days_beyond_terms, ar_days_beyond_terms, dscr
        from scores where group_id = ? and month = cast(? as timestamp)""",
        [group_id, month],
    ).fetchone()
    before = cursor.execute(
        """select level from scores
        where group_id = ? and month = cast(? as timestamp) - interval 6 month""",
        [group_id, month],
    ).fetchone()
    evidence = {
        "liquidity": buffer_days is not None and f"{buffer_days:.0f} days of cash buffer",
        "cash_generation": margin is not None and f"operating margin {margin:.0%}",
        "payment_discipline": ap_days is not None and f"paying {ap_days:.0f} days beyond terms",
        "collections": ar_days is not None and f"collecting {ar_days:.0f} days beyond terms",
        "debt_burden": dscr is not None and f"debt service covered {dscr:.2f}x",
    }
    drivers = cursor.execute(
        """select pillar, score, delta_score from drivers
        where group_id = ? and month = cast(? as timestamp) order by delta_score""",
        [group_id, month],
    ).fetchall()
    findings = []
    for pillar, score, delta in drivers:
        if score is None:
            continue
        moved = f" ({delta:+.0f} this month)" if delta else ""
        detail = f": {evidence[pillar]}" if evidence.get(pillar) else ""
        findings.append(f"{PILLAR_LABELS.get(pillar, pillar)} {score:.0f}{moved}{detail}")
    heading = f", {trend:+.1f} points a month" if trend is not None else ""
    since = f" It was {before[0]:.0f} six months earlier." if before else ""
    return AgentReport(
        agent="score",
        summary=f"Level {level:.0f}, {state.replace('_', ' ')}{heading}, tier {tier}.{since}",
        findings=findings,
    )


def monitor_report(cursor: duckdb.DuckDBPyConnection, group_id: str, month: str) -> AgentReport:
    alerts = cursor.execute(
        """select month, state_from, state_to, onset_month, level_at_onset, level_at_alert,
        driver_1, driver_2, anticipation_months from alerts
        where group_id = ? and month <= cast(? as timestamp) order by month desc""",
        [group_id, month],
    ).fetchall()
    if not alerts:
        return AgentReport(agent="monitor", summary="The monitor has not fired for this group.")
    findings = []
    for fired, state_from, state_to, onset, at_onset, at_alert, d1, d2, months_early in alerts:
        drivers = " and ".join(PILLAR_LABELS.get(d, d) for d in (d1, d2) if d)
        early = f", {months_early:.0f} months before the tier changed" if months_early else ""
        findings.append(
            f"{fired:%Y-%m}: state changed from {state_from} to {state_to}, the move began in "
            f"{onset:%Y-%m} at level {at_onset:.0f} and stood at {at_alert:.0f} when it fired, "
            f"driven by {drivers or 'no single pillar'}{early}"
        )
    return AgentReport(
        agent="monitor",
        summary=f"{len(alerts)} alert{'s' if len(alerts) > 1 else ''}, the latest: {findings[0]}.",
        findings=findings,
    )


def credit_report(cursor: duckdb.DuckDBPyConnection, group_id: str, month: str) -> AgentReport:
    offer = cursor.execute(
        """select eligible, limit_eur, apr, limit_change_eur from offers
        where group_id = ? and month = cast(? as timestamp)""",
        [group_id, month],
    ).fetchone()
    actions = cursor.execute(
        """select pillar, action, expected_level_gain from actions
        where group_id = ? and month = cast(? as timestamp) order by rank""",
        [group_id, month],
    ).fetchall()
    if offer is None:
        summary = "No credit line priced for this month."
    elif not offer[0]:
        summary = "Not eligible for the working-capital line this month."
    else:
        change = f", {offer[3]:+,.0f} EUR on last month" if offer[3] else ""
        rate = f" at {offer[2]:.1%} APR" if offer[2] is not None else ""
        summary = f"Working-capital line of {offer[1]:,.0f} EUR{rate}{change}."
    return AgentReport(
        agent="credit",
        summary=summary,
        findings=[
            f"{action} Expected gain {gain:+.1f} points on {PILLAR_LABELS.get(pillar, pillar)}."
            for pillar, action, gain in actions
        ],
    )


DATA_AGENTS = {"score": score_report, "monitor": monitor_report, "credit": credit_report}


def _timed(run, snapshot: ScoreSnapshot) -> tuple[AgentReport, float]:
    t0 = time.monotonic()
    return run(snapshot), time.monotonic() - t0


def _finished(agent_id: str, report: AgentReport, t0: float, cached: bool) -> dict:
    return {
        "type": "agent",
        "id": agent_id,
        "status": "done",
        "summary": report.summary,
        "findings": report.findings,
        "sources": report.sources,
        "ms": round((time.monotonic() - t0) * 1000),
        "cached": cached,
    }

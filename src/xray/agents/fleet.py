"""The chat: a director runs queries and agents over the whole portfolio, a writer answers.

The director is a loop, not a fixed plan. Each round the model sees the tables, the agents and
what has come back so far, and asks for the next calls: `query`, one read-only SELECT over any
table, or an agent pointed at one group and month. Calls of one round run in parallel. When the
results are enough, a writer answers from them.

Every agent is a purpose, a set of rules and a set of tools. The rules are code and are shown on
screen. Each tool call is an event, so the screen can show what every agent is doing while it
does it. SQL produces the figures. Where the model thinks or writes, its figures are checked
against the tool output it was given: `untraced_figures`.

`run_chat` yields plain dict events: planning, plan, agent, step, suggestion, writing, token,
check, done. Agents run in threads and report through one queue. Searches run in parallel but
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
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import BaseModel, Field, field_validator

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.cache import JsonCache
from xray.agents.context_retrieval import ContextRetrievalAgent
from xray.agents.llm import LLM, build_llm, complete_json
from xray.agents.notifier import parse_request
from xray.agents.peers import PeersAgent, SectorAgent
from xray.scoring.anchors import CAP_LEVEL, CAP_PILLAR_SCORE, CAP_PILLARS, PILLAR_WEIGHTS
from xray.scoring.rules import RULES_FILE, add_rule, load_rules
from xray.settings import Settings

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 2000
MAX_HISTORY_TURNS = 6
MAX_ROUNDS = 4
MAX_CALLS_PER_ROUND = 4
MAX_QUERY_ROWS = 40
QUERY_TIMEOUT_SECONDS = 20.0
DRIVER_WINDOW_MONTHS = 6
CUSTOMERS_SHOWN = 6
MIN_PAID_INVOICES = 6
# Investor screen. A search fund buys one steady, high-margin company; lenders want cover.
SEARCH_FUND_MARGIN = 0.15
SEARCH_FUND_LEVEL = 60
MARGIN_STEADY = 0.05
MIN_COVER = 1.5

# Mirrors of scoring/offer.py for scalar simulations. A test ties them to the engine.
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
        id="query",
        label="Query",
        purpose="Anything the tables hold, across every group and month.",
        rules=[
            "One read-only SELECT per call: nothing is written, nothing outside the data is read.",
            f"At most {MAX_QUERY_ROWS} rows come back, so a question is answered by aggregating.",
            "The model writes the SQL. The database produces every figure.",
            "A query that fails goes back to the director with its error, to be corrected.",
        ],
        tools=[Tool(name="sql", does="runs the SELECT on DuckDB over the parquet tables")],
    ),
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
    FleetMember(
        id="notifier",
        label="Notifier",
        purpose="Who is told, and where, when the monitor fires or the score crosses a line.",
        rules=[
            "A request becomes a rule: channel, what to wait for, groups. The rule is what runs, "
            "never the sentence.",
            "It waits for the monitor's alerts from an urgency up, or for the score to go above "
            "or below a figure.",
            "Urgency is read off the alert: critical is a group entering falling, warning any "
            "other move down, info a move up or a bump that reverted.",
            "No channel named, nothing saved: the user is asked Slack or email. A message that "
            "only names the channel answers that question and completes the rule.",
            "Nothing is sent from here. The notifier delivers when a month lands.",
        ],
        tools=[
            Tool(name="rules.list", does="the rules in force"),
            Tool(name="rules.parse", does="the request as a rule: channel, trigger, groups"),
            Tool(name="rules.add", does="saves the rule to the book"),
        ],
    ),
)
MEMBERS = {member.id: member for member in ROSTER}
# Calls that stand without a scored group: a query, a named company, the rule book.
GROUPLESS = ("query", "market", "notifier")
INVOICE_TOOLS = ("concentration", "payer_scores", "overdue_ranked")
CASH_TOOLS = ("cash_profile", "debt_capacity")

DIRECTOR_PROMPT = """You direct the chat of a financial health monitor over a portfolio of
business groups. Anyone may be asking: a CFO, a lender, an investor. You never answer: you decide
what to run next, and a writer answers from what came back.
Do not use emojis in any generated text.

Two kinds of call:
- `query`: one read-only DuckDB SELECT over the tables below. Use it for the portfolio, several
  groups, rankings, counts, and the raw invoices, transactions, debt and balances. At most {rows}
  rows come back: aggregate, order, and select only the columns the answer needs. A ranking is
  `order by ... limit 10`, never the whole table.
- an agent, pointed at one `group_id` and `month`. Each one has rules it follows; read them
  before calling it:
{roster}

Tables:
{schema}

{notes}
The user is looking at {month}: use that month when the question names none. No data exists
after it for the user: never read a later month.

How to direct:
- Point an agent only at a group id the question names or a result returned. Never guess one.
- Not every group is scored every month. A call that fails with "No score for group ..." names
  the last month the group was scored: re-point the same call at that month, in the next round.
- Never repeat a call that already came back, with the same or a different wording of `why`:
  the results are kept across rounds. `notifier` saves rules: call it once per request. A
  message that only names slack or email, after the notifier asked where, is such a request.
- One round is the norm. Put every call the answer needs in the first round and set `final` to
  true. A second round is only for a call that needs a figure from the first, or to correct one
  that failed. You have {rounds} rounds in all; after the last one the writer answers with what
  there is.
- When what has come back already answers the question, or nothing can, return "calls": [].
  A greeting or a question on how the product works needs no calls.
- Calls of one round run in parallel, at most {calls}.

Answer with one JSON object and nothing else: no words before or after it, no code fence.
{{"purpose": "three to six words on what the question is for", "lens": "cfo", "final": true,
"calls": [{{"tool": "query", "why": "up to twelve words on what to look for", "query": "select 1"}},
{{"tool": "scorecard", "group_id": "GROUP_0001", "month": "2026-08-01", "why": "..."}},
{{"tool": "simulator", "group_id": "GROUP_0001", "month": "2026-08-01", "why": "...",
"what_if": {{"collections": 10}}}}]}}
`lens` is one of cfo, lender, investor. `month` is YYYY-MM-DD, the first day of the month.
Optional on an agent call: `tools`, a list that narrows the agent to some of its tools;
`compare`, another group id for `peers`; `what_if`, an object of pillar name to points moved,
for `simulator` (pillars: liquidity, cash_generation, payment_discipline, collections,
debt_burden); `company`, the real-world company the user names, for `market`: groups are
anonymous ids and `market` runs only with one."""

TABLE_NOTES = """Notes on the data:
- Group ids are upper case, GROUP_0130: write them so in SQL and in calls, whatever the user
  typed (group_0130, the 0130, group 130).
- `month` is a timestamp on the first day of the month: month = '2026-08-01'.
- `scores`: one row per group and month, from the group's first scored month to its last. A
  group may have no row for the month on screen. `level` is the 0-100 health score, `trend` its
  points a month, `state` one of healthy, stable, improving, bending, falling, weak,
  not_enough_data, `tier` one of healthy, coping, vulnerable. The five pillar columns are 0-100.
  A change over N months is a self join: past.month = now.month - interval N month.
- `drivers`: one row per group, month and pillar, with its contribution to the level.
- `alerts`: only the months the monitor fired, never a history of levels.
  `anticipation_months` is how early it fired, against the tier change. Urgency of an alert:
  critical when the group enters falling, warning for any other move down, info for a move up.
- `groups.name` is the group id again; `country` can be null; `has_erp` says whether the group
  has invoices.
- `payers`: customers of a group as of a month, only for groups with invoices (`has_erp`).
- `offers`, `actions`: the working-capital line and the ranked next moves, per group and month.
- `companies`: the companies inside each group.
- `invoices`, `transactions`, `balances`, `debt_products`, `banking_products`, when listed, are
  the raw trail per company. They are large: always filter or aggregate. `balances` is a single
  snapshot at 2026-09-01.
- Amounts in `_eur` columns are euros."""

INTERPRET_PROMPT = """You are the {label} agent inside a financial health monitor. The director
asks you: "{ask}". Answer it in at most two sentences from the tool output below. Copy every
figure exactly as it is written there: never compute, convert or round a new one. If the output
does not hold the answer, say so. Plain text, no emojis, in the language of the ask."""

WRITER_PROMPT = """You are Lighthouse, the analyst inside a financial health monitor over a
portfolio of business groups. The person asking is read as: {lens}. Answer the question using
only the results below: queries over the data and agent reports. Lead with the answer in one
sentence. Then the evidence, with the numbers from the results. End with ranked moves only when
the question asks what to do.

Every figure you write is checked against the results after you finish: copy figures exactly as
they are written there, and never compute, convert or round a new one. Do not add, average,
count or subtract figures: when a total is not in the results, give the parts. State only what
the results say: no distribution, streak, cause or intent they do not spell out.

A line starting with "failed:" is a call that did not run, not a fact about the group: never
quote it. When the results do not hold the answer, say so in one or two sentences and stop: no
evidence section, no instructions on what to run or check. Two exceptions: when the results
answer the question as it applies to the group (its own country when another was asked about),
give that and say so; when a group has results at an earlier month than the one on screen,
answer from that month and name it.

How the score works, for questions about it: a 0-100 level per group and month, from five
pillars (liquidity, cash generation, payment discipline, collections, debt burden), never fitted
to the portfolio. States: a bump is one bad month that recovers; bending is a sustained early
decline while the level still looks fine; falling is structural decline; improving is a
sustained rise. Alert urgency: critical is a group entering falling, warning any other move down,
info a move up or a bump that reverted: a rule for critical alerts is a rule for groups starting
to fall. When the notifier reports nothing saved yet and asks where, say what it would watch and
end with the question "Slack or email?" in those words. A draft suggestion, when present, is
shown to the user under your answer: refer to it, do not repeat it.

Plain text, short paragraphs, no markdown, no headings, no em dashes, no emojis. A list goes one item per
line. At most 180 words. Answer in the language of the question."""

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
# A month the director wrote starts with its year and month; anything else is dropped.
MONTH_SPELLING = re.compile(r"\d{4}-\d{2}")
# Digits inside an id (GROUP_0220) are a name, not a figure.
FIGURE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
# A month or a date (2026-06, 2026-06-01) is a name too.
DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
# The director's fallback when there is no model: purpose, pattern, lens, agent to its tools.
PURPOSE_RULES: tuple[tuple[str, str, Lens, dict[str, list[str]]], ...] = (
    (
        "setting up alerts",
        r"slack|e-?mail|correo|notify|av[ií]s|alert me|tell me|let me know|ping me|alert rules"
        r"|alarm|alerta|an alert|alert (?:when|if)",
        "cfo",
        {"notifier": []},
    ),
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
# What the fallback reads when the question names no group.
PORTFOLIO_QUERY = """select state, count(*) as groups, round(avg(level)) as average_level
from scores where month = cast('{month}' as timestamp) group by state order by groups desc"""
# A group as the user typed it (group_0130) or by its digits alone (0130). Bind the word twice.
SAME_GROUP = "(lower(group_id) = lower(?) or group_id = 'GROUP_' || ?)"
# The writer's answer when the notifier had no channel to save a rule under.
ASKED_WHERE = re.compile(r"slack or e-?mail", re.I)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """One question about the portfolio as of one month, with the recent turns for follow-ups."""

    message: str
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


class Call(BaseModel):
    """One thing the director asks for: a query, or an agent pointed at a group and month."""

    tool: str
    why: str = ""
    query: str | None = None
    group_id: str | None = None
    month: str | None = None
    tools: list[str] = Field(default_factory=list)
    compare: str | None = None
    company: str | None = None
    what_if: dict[str, float] = Field(default_factory=dict)

    @field_validator("what_if", mode="before")
    @classmethod
    def _pillar_to_points(cls, value: Any) -> Any:
        """Models also write {"pillar": "collections", "points": 10}, alone or in a list."""
        if value is None:
            return {}
        moves = value if isinstance(value, list) else [value]
        if moves and all(isinstance(m, dict) and "pillar" in m for m in moves):
            return {m["pillar"]: m.get("points", m.get("delta", 0)) for m in moves}
        return value


class Move(BaseModel):
    """One round of the director. No calls means the results are enough to answer."""

    purpose: str = ""
    lens: Lens = "cfo"
    final: bool = False
    calls: list[Call] = Field(default_factory=list)


@dataclass
class Step:
    """One tool call in flight. Set `output` before the block ends."""

    output: str = ""


@dataclass
class AgentContext:
    """What an agent needs to run and to report what it is doing."""

    run_id: str
    call: Call
    request: ChatRequest
    snapshot: ScoreSnapshot
    db: duckdb.DuckDBPyConnection
    settings: Settings
    llm: LLM | None
    has_erp: bool
    emit: Callable[[dict], None]
    lens: Lens = "cfo"
    facts: dict[str, Any] = field(default_factory=dict)
    steps: int = 0

    @property
    def ask(self) -> str:
        return self.call.why

    def wants(self, tool: str) -> bool:
        """The director may narrow an agent to some of its tools. No list means all of them."""
        return not self.call.tools or tool in self.call.tools

    def money(self, eur: float, signed: bool = False) -> str:
        """An amount held in euros, shown in the currency the user picked, at the month's year."""
        code = self.request.currency
        value = eur * display_rate(code, int(self.snapshot.month[:4]))
        return f"{value:+,.0f} {code}" if signed else f"{value:,.0f} {code}"

    def query(self, sql: str, params: list | None = None) -> list[tuple]:
        """Run SQL with (group_id, month) bound unless other params are given."""
        bound = [self.call.group_id, self.call.month] if params is None else params
        return self.db.execute(sql, bound).fetchall()

    @contextmanager
    def tool(self, name: str, **inputs: Any) -> Iterator[Step]:
        self.steps += 1
        n, t0, step = self.steps, time.monotonic(), Step()
        shown = ", ".join(f"{key}={value}" for key, value in inputs.items())
        base = {"type": "step", "run": self.run_id, "n": n, "tool": name, "input": shown}
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
    """Direct, run the calls, direct again until the results are enough, suggest, write, check."""
    started = time.monotonic()
    request = request.model_copy(update={"month": _month(request.month)})
    llm = build_llm(settings, reasoning_effort="low")
    schema = describe_tables(db.cursor())

    events: queue.Queue[dict] = queue.Queue()
    results: list[tuple[Call, str]] = []
    facts: dict[str, Any] = {}
    lens: Lens = "cfo"
    with ThreadPoolExecutor(max_workers=MAX_CALLS_PER_ROUND) as pool:
        for round_no in range(1, MAX_ROUNDS + 1):
            yield {"type": "planning"}
            move = direct(request, schema, results, llm, db.cursor(), round_no)
            if not move.calls:
                break
            lens = move.lens
            first = len(results) + 1
            runs = {str(first + i): call for i, call in enumerate(move.calls)}
            yield {
                "type": "plan",
                "purpose": move.purpose,
                "agents": [
                    {"run": run_id, "id": call.tool, "reason": call.why, "target": _target(call)}
                    for run_id, call in runs.items()
                ],
            }
            running: dict[Future, str] = {}
            failed = False
            for run_id, call in runs.items():
                cursor = db.cursor()
                snapshot, has_erp = load_snapshot(cursor, call)
                blank = ScoreSnapshot(
                    group_id=call.group_id or "", month=(call.month or request.month)[:7], level=0
                )
                ctx = AgentContext(
                    run_id, call, request, snapshot or blank, cursor, settings, llm, has_erp,
                    events.put, lens, facts,
                )  # fmt: skip
                agent = AGENTS[call.tool] if snapshot or call.tool in GROUPLESS else _no_score
                running[pool.submit(_timed, agent, ctx)] = run_id
            while running:
                yield from _drain(events)
                for future in [f for f in running if f.done()]:
                    run_id = running.pop(future)
                    yield from _drain(events)
                    outcome = _outcome(run_id, runs[run_id].tool, future)
                    results.append((runs[run_id], _result_text(outcome)))
                    failed |= outcome["status"] == "failed"
                    yield outcome
                time.sleep(0.02)
            # A final round with a failed call gets one more: the director corrects it.
            if move.final and not failed:
                break

    suggestion = draft_suggestion(request, facts)
    if suggestion:
        yield {"type": "suggestion"} | suggestion

    yield {"type": "writing"}
    writing = time.monotonic()
    source, answer = writer_input(request, results, suggestion), ""
    try:
        for text in write(lens, results, source, llm):
            answer += text
            yield {"type": "token", "text": text}
    except Exception as e:  # the trace above already holds the evidence
        logger.warning("Writer failed: %s", e)
        yield {"type": "error", "message": "The writer could not finish. The results stand."}
    else:
        untraced = untraced_figures(answer, source)
        yield {
            "type": "check",
            "figures": len(_figures(answer)),
            "untraced": untraced,
            "ms": _ms(writing),
        }
    yield {"type": "done", "ms": _ms(started)}


def describe_tables(cursor: duckdb.DuckDBPyConnection) -> str:
    """Every table the chat can query, one line each with its columns and types."""
    rows = cursor.execute(
        """select table_name, string_agg(column_name || ' ' || lower(data_type), ', '
            order by ordinal_position)
        from information_schema.columns group by 1 order by 1"""
    ).fetchall()
    return "\n".join(f"- {table}: {columns}" for table, columns in rows)


def mentioned_groups(
    request: ChatRequest, cursor: duckdb.DuckDBPyConnection
) -> list[tuple[str, str]]:
    """The groups the question names by id, as the tables spell them, each with its last scored
    month at or before the month on screen. In the order named."""
    found = []
    for word in dict.fromkeys(MENTION.findall(request.message)):
        row = cursor.execute(
            f"""select group_id, max(month) from scores
            where {SAME_GROUP} and month <= cast(? as timestamp) group by 1""",
            [word, word, request.month],
        ).fetchone()
        if row:
            found.append((row[0], f"{row[1]:%Y-%m-%d}"))
    return found


def direct(
    request: ChatRequest,
    schema: str,
    results: list[tuple[Call, str]],
    llm: LLM | None,
    cursor: duckdb.DuckDBPyConnection,
    round_no: int = 1,
) -> Move:
    """Ask the model what to run next. Without it, or if it fails on the first round, rules.

    An answer that is not a valid move is sent back once with its error before giving up.
    """
    move = None
    if llm:
        roster = "\n".join(
            f"  - {m.id}: {m.purpose} Tools: "
            + "; ".join(f"{t.name} ({t.does})" for t in m.tools)
            + "".join(f"\n    Rule: {rule}" for rule in m.rules)
            for m in ROSTER
            if m.id != "query"
        )
        system = DIRECTOR_PROMPT.format(
            rows=MAX_QUERY_ROWS,
            roster=roster,
            schema=schema,
            notes=TABLE_NOTES,
            month=request.month,
            calls=MAX_CALLS_PER_ROUND,
            rounds=MAX_ROUNDS,
        )
        history = "\n".join(f"{turn.role}: {turn.content}" for turn in request.history)
        user = (
            (f"Earlier in this conversation:\n{history}\n\n" if history else "")
            + f"Question: {request.message}"
            + ("\n\nWhat has come back so far:\n\n" + _transcript(results) if results else "")
            + f"\n\nRound {round_no} of {MAX_ROUNDS}."
        )
        for _ in range(2):
            try:
                move = complete_json(llm, system, user, Move)
                break
            except ValueError as e:  # not a move: the model gets its error back, once
                logger.warning("Director failed on round %s: %s", round_no, e)
                user += (
                    f"\n\nYour previous answer could not be read as a move: {str(e)[:300]}\n"
                    "Answer again with one JSON object of the shape given, and nothing else."
                )
            except Exception as e:  # the model is down: a bad move must not cost the answer
                logger.warning("Director failed on round %s: %s", round_no, e)
                break
    if move is None:
        move = Move() if results else fallback_move(request, cursor)
    calls = [_checked(call, request, cursor) for call in move.calls]
    known = [call for call in calls if call is not None][:MAX_CALLS_PER_ROUND]
    return move.model_copy(update={"calls": known})


def _checked(call: Call, request: ChatRequest, cursor: duckdb.DuckDBPyConnection) -> Call | None:
    """A call the fleet can run, or None. The month is normalised and never later than the one
    on screen; group ids are spelled as the tables spell them."""
    if call.tool not in AGENTS:
        return None
    if call.tool == "query":
        return call if call.query else None
    if call.tool == "market" and not call.company:
        return None
    on_screen = _month(request.month)
    month = _month(call.month) if call.month and MONTH_SPELLING.match(call.month) else on_screen
    tools = [t for t in call.tools if t in {tool.name for tool in MEMBERS[call.tool].tools}]
    what_if = {p: points for p, points in call.what_if.items() if p in PILLAR_LABELS}
    return call.model_copy(
        update={
            "group_id": _spelled(cursor, call.group_id),
            "compare": _spelled(cursor, call.compare),
            "month": min(month, on_screen),
            "tools": tools,
            "what_if": what_if,
        }
    )


def _spelled(cursor: duckdb.DuckDBPyConnection, group_id: str | None) -> str | None:
    """The id as the tables spell it (GROUP_0130 for group_0130 or 0130), or as given when
    unknown."""
    if not group_id:
        return group_id
    word = group_id.strip()
    row = cursor.execute(f"select group_id from groups where {SAME_GROUP}", [word, word]).fetchone()
    return row[0] if row else group_id


def fallback_move(request: ChatRequest, cursor: duckdb.DuckDBPyConnection) -> Move:
    """The rules that stand in for the model: the named group's agents, or the portfolio."""
    move = Move(purpose="why the score moved", final=True)
    picked: dict[str, list[str]] = {}
    for purpose, pattern, lens, tools in PURPOSE_RULES:
        if re.search(pattern, request.message, re.I):
            move.purpose, move.lens, picked = purpose, lens, dict(tools)
            break
    groups = mentioned_groups(request, cursor)
    if not groups:
        move.calls = [Call(tool=agent) for agent in picked if agent == "notifier"]
        if not move.calls:
            query = PORTFOLIO_QUERY.format(month=request.month)
            move.purpose = "the portfolio this month"
            move.calls = [Call(tool="query", why="the portfolio by state", query=query)]
        return move
    (group_id, month), *others = groups
    compare = others[0][0] if others else None
    if compare:
        picked["peers"] = list(dict.fromkeys([*picked.get("peers", ["standing"]), "compare"]))
    move.calls = [
        Call(tool=agent, group_id=group_id, month=month, tools=tools, compare=compare)
        for agent, tools in ({"scorecard": []} | picked).items()
    ]
    return move


def run_query(ctx: AgentContext) -> AgentReport:
    """One SELECT the director wrote. Rows come back as text, which the figure check reads."""
    sql = (ctx.call.query or "").strip().rstrip(";")
    with ctx.tool("sql", query=" ".join(sql.split())) as step:
        statements = duckdb.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("Only one SELECT statement is allowed.")
        watchdog = threading.Timer(QUERY_TIMEOUT_SECONDS, ctx.db.interrupt)
        watchdog.start()
        try:
            result = ctx.db.execute(sql)
            columns = [column[0] for column in result.description]
            rows = result.fetchmany(MAX_QUERY_ROWS + 1)
        finally:
            watchdog.cancel()
        cut = len(rows) > MAX_QUERY_ROWS
        rows = rows[:MAX_QUERY_ROWS]
        step.output = f"{len(rows)} rows" + (", more were cut" if cut else "")
    summary = f"{len(rows)} row{'' if len(rows) == 1 else 's'} of {', '.join(columns)}."
    if cut:
        summary += f" Only the first {MAX_QUERY_ROWS} are shown: the query needs a tighter filter."
    return AgentReport(
        agent="query",
        summary=summary,
        findings=[
            ", ".join(
                f"{column} {_cell(value)}" for column, value in zip(columns, row, strict=True)
            )
            for row in rows
        ],
    )


def _cell(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, datetime):
        return f"{value:%Y-%m-%d}"
    if isinstance(value, float):
        return f"{value:,.0f}" if abs(value) >= 1000 else f"{value:.4g}"
    return str(value)


def _month(month: str) -> str:
    """Any spelling of a month (2026-08, 2026-08-01 00:00:00) as the first day of it."""
    return f"{month[:7]}-01"


def _target(call: Call) -> str | None:
    return f"{call.group_id}, {call.month[:7]}" if call.group_id and call.month else None


def _result_text(outcome: dict) -> str:
    if outcome["status"] == "failed":
        return f"failed: {outcome['error']}"
    return "\n".join([outcome["summary"], *outcome["findings"]])


def _transcript(results: list[tuple[Call, str]]) -> str:
    sections = []
    for call, text in results:
        what = call.query if call.tool == "query" else _target(call) or ""
        sections.append(f"## {MEMBERS[call.tool].label}: {what}\n{text}")
    return "\n\n".join(sections)


def draft_suggestion(request: ChatRequest, facts: dict[str, Any]) -> dict | None:
    """The one action to put in front of a person. Built from figures, never from the model."""
    if not ACTION_WORDS.search(request.message):
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
    request: ChatRequest, results: list[tuple[Call, str]], suggestion: dict | None
) -> str:
    """Everything the writer may quote. The figure check reads the same text."""
    history = "\n".join(f"{turn.role}: {turn.content}" for turn in request.history)
    draft = (
        f"\n\nDraft suggestion shown to the user: {suggestion['title']}. {suggestion['detail']}"
        if suggestion
        else ""
    )
    return (
        f"The user is looking at month {request.month[:7]}.\n\n"
        + (_transcript(results) or "Nothing was run for this question.")
        + draft
        + (f"\n\nEarlier in this conversation:\n{history}" if history else "")
        + f"\n\nQuestion: {request.message}"
    )


def write(
    lens: Lens, results: list[tuple[Call, str]], source: str, llm: LLM | None
) -> Iterator[str]:
    if llm is None:
        yield " ".join(text.split("\n", 1)[0] for _, text in results)
        return
    yield from llm.stream(WRITER_PROMPT.format(lens=lens), source)


def _figures(text: str) -> list[tuple[str, float, int]]:
    """Every figure that is not a small count or a date: as written, its value, its decimals."""
    found = []
    for raw in FIGURE.findall(DATE.sub(" ", text)):
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
        system = INTERPRET_PROMPT.format(label=MEMBERS[ctx.call.tool].label, ask=ctx.ask)
        try:
            answer = ctx.llm.complete(system, output).strip()
        except Exception as e:  # the figures stand without the thought
            logger.warning("Agent %s could not think: %s", ctx.call.tool, e)
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
    cursor: duckdb.DuckDBPyConnection, call: Call
) -> tuple[ScoreSnapshot | None, bool]:
    group_id, month = call.group_id, call.month
    if not group_id:
        return None, False
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
    if any(ctx.wants(tool) for tool in INVOICE_TOOLS):
        if ctx.has_erp:
            _customers(ctx, summary, findings)
        else:
            summary.append(
                f"{ctx.call.group_id} has no ERP connected, so there are no invoices: "
                "its customers, their lateness and what is overdue cannot be read."
            )
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
    moves = {p: points for p, points in ctx.call.what_if.items() if p in ctx.snapshot.pillars}
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
    if ctx.call.compare and ctx.wants("compare"):
        findings += _compare(ctx, ctx.call.compare, summary)
    if ctx.lens == "investor" and ctx.wants("screen"):
        findings.append(_screen(ctx, summary))
    if ctx.wants("comparables"):
        with ctx.tool("comparables", country=ctx.snapshot.country) as step:
            similar = ctx.query(
                """select count(*) from groups g,
                    (select annual_revenue_eur r, country c from groups where group_id = $1) me
                where g.group_id <> $1 and g.country is not distinct from me.c
                  and g.annual_revenue_eur between me.r / 3 and me.r * 3""",
                [ctx.call.group_id],
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
        scored = ctx.query(
            """select level, trend, state from scores
            where group_id = ? and month = cast(? as timestamp)""",
            [other, ctx.call.month],
        )
        if not scored:
            raise ValueError(f"No score for group {other} in {ctx.snapshot.month} to compare with.")
        level, trend, state = scored[0]
        theirs = dict(
            ctx.query(
                """select pillar, score from drivers where group_id = ?
                and month = cast(? as timestamp) and score is not null""",
                [other, ctx.call.month],
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
        # Each test named by what is wrong when it fails, so "fails it on: ..." reads straight.
        tests = {
            f"{n_companies} companies, not one": n_companies == 1,
            f"margin {margin or 0:.0%}, under {SEARCH_FUND_MARGIN:.0%}": (margin or 0)
            >= SEARCH_FUND_MARGIN,
            "margin not steady over the year": steadiness is not None
            and steadiness < MARGIN_STEADY,
            f"level {level:.0f}, under {SEARCH_FUND_LEVEL}": level >= SEARCH_FUND_LEVEL,
            f"state {state}": state not in ("bending", "falling"),
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
            [ctx.call.month],
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
    named = ctx.snapshot.model_copy(update={"name": ctx.call.company})
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


def pending_request(history: list[ChatTurn]) -> str:
    """The request the assistant just asked where to send, or nothing."""
    if len(history) >= 2 and ASKED_WHERE.search(history[-1].content):
        return history[-2].content
    return ""


# One writer at a time on the rule book: the director dispatches a round in parallel threads.
_RULE_BOOK = threading.Lock()


def notifier(ctx: AgentContext) -> AgentReport:
    """Who is told when the monitor fires. Reads the rule book, and adds to it when asked.

    A request that names no channel is not saved: the report asks Slack or email, and the next
    message that answers completes it from the turn before.
    """
    path = ctx.settings.serving_dir / RULES_FILE
    with ctx.tool("rules.list") as step:
        rules = load_rules(path)
        step.output = f"{len(rules)} rules in force"
    earlier = pending_request(ctx.request.history)
    text = f"{earlier} {ctx.request.message}" if earlier else ctx.request.message
    with ctx.tool("rules.parse", by="model" if ctx.llm else "patterns") as step, SerialLLM._lock:
        asked = [
            p.model_copy(
                update={"groups": list(dict.fromkeys(_spelled(ctx.db, g) for g in p.groups))}
            )
            for p in parse_request(ctx.request.message, ctx.call.group_id, ctx.llm, earlier)
        ]
        step.output = (
            "; ".join(f"{p.wanted()} to {p.channel or 'a channel not said'}" for p in asked)
            or "no delivery asked for"
        )
    saved = []
    # The director may ask twice for the same thing, and its calls run in parallel: one writer at
    # a time, and the book is read again inside the lock so the second call sees the first.
    with _RULE_BOOK:
        rules = load_rules(path)
        for parsed in asked:
            if parsed.channel is None:
                saved.append(f"Nothing saved yet: {parsed.wanted()}. Slack or email?")
                continue
            rule = parsed.rule(text)
            if same := next((r for r in rules if r.describe() == rule.describe()), None):
                saved.append(
                    f"Already in force as rule {same.id}: {same.describe()}. Nothing added."
                )
                continue
            with ctx.tool("rules.add", channel=rule.channel) as step:
                rule = add_rule(path, rule)
                step.output = f"rule {rule.id} saved"
            saved.append(f"Saved rule {rule.id}: {rule.describe()}.")
            rules.append(rule)
    standing = (
        f"{len(rules)} rule{'s' if len(rules) != 1 else ''} in force."
        if rules
        else "No alert rules yet: nothing leaves the monitor until one is set."
    )
    return AgentReport(
        agent="notifier",
        summary=" ".join([*saved, standing]),
        findings=[f"Rule {r.id}: {r.describe()}." for r in rules],
    )


AGENTS: dict[str, Callable[[AgentContext], AgentReport]] = {
    "query": run_query,
    "scorecard": scorecard,
    "ledger": ledger,
    "simulator": simulator,
    "peers": peers,
    "macro": macro,
    "market": market,
    "notifier": notifier,
}


def _no_score(ctx: AgentContext) -> AgentReport:
    """The error the director reads to re-point the call: the month the group was last scored."""
    group_id, month = ctx.call.group_id, ctx.snapshot.month
    if not group_id:
        raise ValueError(f"{ctx.call.tool} needs a group_id and a month: none was given.")
    before, first = ctx.db.execute(
        """select max(month) filter (where month <= cast(? as timestamp)), min(month)
        from scores where group_id = ?""",
        [ctx.call.month, group_id],
    ).fetchone()
    if first is None:
        raise ValueError(f"No group {group_id} in the portfolio: check the id.")
    when = (
        f"its last scored month before that is {before:%Y-%m}"
        if before
        else f"its first scored month is {first:%Y-%m}, after the month on screen"
    )
    raise ValueError(f"No score for group {group_id} in {month}: {when}.")


def _timed(
    run: Callable[[AgentContext], AgentReport], ctx: AgentContext
) -> tuple[AgentReport, int]:
    t0 = time.monotonic()
    return run(ctx), _ms(t0)


def _outcome(run_id: str, agent_id: str, future: Future) -> dict:
    base = {"type": "agent", "run": run_id, "id": agent_id}
    try:
        report, ms = future.result()
    except Exception as e:  # one call failing must not cost the answer
        logger.warning("Agent %s failed: %s", agent_id, e)
        return base | {"status": "failed", "error": str(e)[:300]}
    return base | {
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

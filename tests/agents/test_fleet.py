import duckdb
import pytest

from xray.agents.base import ScoreSnapshot
from xray.agents.fleet import (
    AGENTS,
    LIMIT_CURVE,
    MIN_COMPOUND,
    AgentContext,
    ChatRequest,
    Plan,
    level_of,
    limit_factor,
    make_plan,
    run_chat,
    untraced_figures,
)
from xray.scoring import offer
from xray.settings import Settings

MONTH = "2026-03-01 00:00:00"


@pytest.fixture
def db():
    """One group, bending: level 68 from 80, payment discipline dropped, one alert, one offer."""
    con = duckdb.connect()
    con.sql(
        "create table groups (group_id text, name text, country text, sector text,"
        " has_erp boolean, n_companies int, annual_revenue_eur double)"
    )
    con.sql("insert into groups values ('g1', 'Example Corp', 'ES', null, true, 1, 1200000)")
    con.sql(
        """create table scores (group_id text, month timestamp, level double, trend double,
        state text, tier text, buffer_days double, operating_margin double,
        ap_days_beyond_terms double, ar_days_beyond_terms double, dscr double,
        monthly_inflow_eur double)"""
    )
    con.sql(
        f"""insert into scores values
        ('g1', '{MONTH}', 68, -2, 'bending', 'coping', 40, 0.08, 21, null, 1.4, 100000),
        ('g1', '2025-09-01', 80, 0, 'healthy', 'healthy', 60, 0.1, 2, null, 1.6, 100000)"""
    )
    con.sql(
        "create table drivers (group_id text, month timestamp, pillar text, score double,"
        " delta_score double, contribution double)"
    )
    con.sql(
        f"""insert into drivers values ('g1', '{MONTH}', 'collections', 41, -15, -6),
        ('g1', '2025-09-01', 'collections', 70, 0, 1),
        ('g1', '{MONTH}', 'liquidity', null, null, null)"""
    )
    con.sql(
        """create table alerts (group_id text, month timestamp, kind text, direction text,
        state_from text, state_to text, onset_month timestamp, level_at_onset double,
        level_at_alert double, driver_1 text, driver_2 text, anticipation_months double)"""
    )
    con.sql(
        f"""insert into alerts values ('g1', '{MONTH}', 'state', 'down', 'healthy', 'bending',
        '2025-12-01', 80, 68, 'collections', null, 3)"""
    )
    con.sql(
        "create table offers (group_id text, month timestamp, eligible boolean, limit_eur double,"
        " apr double, limit_change_eur double)"
    )
    con.sql(f"insert into offers values ('g1', '{MONTH}', true, 250000, 0.07, -50000)")
    con.sql(
        'create table actions (group_id text, month timestamp, "rank" bigint, pillar text,'
        " action text, expected_level_gain double)"
    )
    con.sql(
        f"""insert into actions values
        ('g1', '{MONTH}', 1, 'collections', 'Chase the oldest receivables.', 1.5)"""
    )
    con.sql(
        """create table payers (group_id text, month timestamp, name text, share_of_billing double,
        overdue_eur double, oldest_overdue_days int, days_late double, days_late_change double,
        payer_score double, reliable boolean)"""
    )
    con.sql(
        f"""insert into payers values
        ('g1', '{MONTH}', 'Customer 1', 0.6, 40000, 90, 25, 12, 60, true),
        ('g1', '{MONTH}', 'Customer 2', 0.004, 0, null, 1, null, 99, true)"""
    )
    return con


def no_keys(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        serving_dir=tmp_path,
        helmcode_api_key=None,
        exa_api_key=None,
        tavily_api_key=None,
    )


def run(db, tmp_path, message: str, currency: str = "EUR") -> list[dict]:
    request = ChatRequest(message=message, group_id="g1", month=MONTH, currency=currency)
    return list(run_chat(request, db, no_keys(tmp_path)))


def done(events: list[dict]) -> dict[str, dict]:
    return {e["id"]: e for e in events if e["type"] == "agent" and e["status"] == "done"}


def test_chat_without_a_model_plans_by_rules_and_answers_from_the_reports(db, tmp_path):
    events = run(db, tmp_path, "  Is this a bump or a fall?  ")

    assert [e["type"] for e in events][:2] == ["planning", "plan"]
    assert events[1]["lens"] == "cfo"
    score = done(events)["scorecard"]["summary"]
    assert score.startswith("Level 68, bending, -2.0 points a month, tier coping.")
    assert "It was 80 six months earlier, moved by collections -7.0." in score
    assert "2nd best month of 2" in score
    findings = done(events)["scorecard"]["findings"]
    assert findings[:2] == [
        "collections 41 (-15 this month)",
        "No data for liquidity, cash generation, payment discipline, debt burden: "
        "the weight moved to the others.",
    ]
    assert "from healthy to bending" in findings[2]
    assert "3 months before the tier changed" in findings[2]
    answer = "".join(e["text"] for e in events if e["type"] == "token")
    assert "Level 68" in answer
    assert [e["type"] for e in events][-2:] == ["check", "done"]
    assert events[-2]["untraced"] == []


def test_every_tool_call_is_a_step_that_starts_and_ends(db, tmp_path):
    events = run(db, tmp_path, "why did the score move?")

    steps = [e for e in events if e["type"] == "step" and e["agent"] == "scorecard"]
    assert [(s["tool"], s["status"]) for s in steps] == [
        (tool, status)
        for tool in ("pillars_at", "drivers_window", "own_history_rank", "alerts_for")
        for status in ("running", "done")
    ]
    assert steps[1]["output"] == "level 68, bending, 1 of 5 pillars"


def test_director_follows_up_with_the_ledger_when_collections_drags(db, tmp_path):
    events = run(db, tmp_path, "what is our credit line and what should we do?")

    assert [a["id"] for a in events[1]["agents"]] == ["scorecard", "simulator"]
    follow_up = next(e for e in events if e["type"] == "dispatch")
    assert [a["id"] for a in follow_up["agents"]] == ["ledger"]
    ledger = done(events)["ledger"]
    assert ledger["summary"] == (
        "Customer 1 is 60% of billing and the top five are 60%. "
        "40,000 EUR is overdue across 1 customers."
    )
    assert "Customer 2: under 1% of billing, pays 1 day late, payer score 99" in ledger["findings"]
    # The planner narrowed the ledger to invoices: cash and debt were not asked for.
    assert not [e for e in events if e["type"] == "step" and e["tool"] == "cash_profile"]
    suggestion = next(e for e in events if e["type"] == "suggestion")
    assert suggestion["title"] == "Chase Customer 1 this week"


def test_investor_lens_screens_the_group_and_sizes_its_debt_capacity(db, tmp_path):
    events = run(db, tmp_path, "would a search fund buy this company?")

    assert events[1]["lens"] == "investor"
    assert (
        "fails it on: margin 15% or more, not bending or falling"
        in (done(events)["peers"]["summary"])
    )
    # 1.2m revenue at a 9% margin is 108,000 of cash: at 1.5x cover it carries 72,000 of debt
    # service against 77,143 today, so there is no headroom.
    assert any("carries 0 EUR more debt service" in f for f in done(events)["ledger"]["findings"])
    assert not [e for e in events if e["type"] == "suggestion"]


def test_a_group_named_with_a_dollar_is_compared_at_the_same_month(db, tmp_path):
    db.sql(
        f"""insert into scores values
        ('g2', '{MONTH}', 80, 1, 'healthy', 'healthy', 60, 0.1, 2, null, 1.6, 9)"""
    )
    db.sql(f"insert into drivers values ('g2', '{MONTH}', 'collections', 75, 0, 3)")

    events = run(db, tmp_path, "how do we look next to $g2 and $nobody?")

    assert events[1]["compare"] == "g2"
    peers = done(events)["peers"]
    assert "g2 is at level 80, healthy, +1.0 points a month, against 68 here." in peers["summary"]
    assert "collections: 41 here, 75 at g2" in peers["findings"]


def test_chat_reports_an_unknown_group(db, tmp_path):
    request = ChatRequest(message="hi", group_id="nope", month=MONTH)

    events = list(run_chat(request, db, no_keys(tmp_path)))

    assert [e["type"] for e in events] == ["error"]


class TestPlanner:
    def ask(self, llm_answer: str | Exception, message: str = "why?", has_erp: bool = True):
        class FakeLLM:
            def complete(self, system, user):
                if isinstance(llm_answer, Exception):
                    raise llm_answer
                return llm_answer

        snapshot = ScoreSnapshot(group_id="g1", month="2026-03", level=68, name="Example Corp")
        request = ChatRequest(message=message, group_id="g1", month=MONTH)
        return make_plan(request, snapshot, has_erp, FakeLLM())

    def test_keeps_known_agents_and_tools_in_roster_order_and_always_adds_scorecard(self):
        plan = self.ask(
            '{"lens": "lender", "purpose": "renewing the line", "agents": ["macro", "made_up",'
            ' "ledger"], "tools": {"ledger": ["cash_profile", "made_up"]}}'
        )

        assert plan.agents == ["scorecard", "ledger", "macro"]
        assert plan.tools == {"ledger": ["cash_profile"]}
        assert plan.lens == "lender"

    def test_market_runs_only_for_a_named_company(self):
        assert self.ask('{"agents": ["market"]}').agents == ["scorecard"]
        assert self.ask('{"agents": ["market"], "company": "Cabify"}').agents == [
            "scorecard",
            "market",
        ]

    def test_a_group_without_invoices_keeps_the_ledger_only_for_cash(self):
        chase = self.ask(
            '{"agents": ["ledger"], "tools": {"ledger": ["overdue_ranked"]}}', has_erp=False
        )  # noqa: E501
        cash = self.ask('{"agents": ["ledger"]}', has_erp=False)

        assert chase.agents == ["scorecard"]
        assert cash.tools["ledger"] == ["cash_profile", "debt_capacity"]

    def test_falls_back_to_rules_when_the_model_fails(self):
        plan = self.ask(RuntimeError("down"), message="Is the sector moving too?")

        assert plan.agents == ["scorecard", "macro"]
        assert plan.purpose == "us or the market"


class TestFigures:
    def test_a_figure_traces_at_the_precision_it_was_written_with(self):
        source = "Level 68.4, line of 250,000 EUR at 7.0% APR, 3 alerts in 2026-03"

        assert untraced_figures("Level 68, a line of 250,000 EUR, 3 alerts.", source) == []
        assert untraced_figures("Level 70 and 1.2 million EUR.", source) == ["70", "1.2"]

    def test_a_thought_with_a_new_figure_never_leads_the_report(self, db, tmp_path):
        class Inventive:
            def complete(self, system, user):
                return "Customer 1 owes 99,999 EUR."

        plan = Plan(agents=["ledger"], asks={"ledger": "who owes the most?"})
        request = ChatRequest(message="who owes?", group_id="g1", month=MONTH)
        snapshot = ScoreSnapshot(group_id="g1", month="2026-03", level=68)
        steps: list[dict] = []
        ctx = AgentContext(
            "ledger", request, snapshot, db, no_keys(tmp_path), Inventive(), plan, True,
            steps.append,
        )  # fmt: skip

        report = AGENTS["ledger"](ctx)

        assert report.summary.startswith("Customer 1 is 60% of billing")
        assert "dropped: 99,999" in steps[-1]["output"]


class TestSimulator:
    def test_the_what_if_runs_the_contract_of_the_engine(self):
        assert LIMIT_CURVE == tuple(tuple(side) for side in offer.LIMIT_CURVE)
        assert MIN_COMPOUND == offer.MIN_COMPOUND
        # liquidity under 25 caps a level that would otherwise sit above 50
        assert level_of({"liquidity": 20, "collections": 100, "cash_generation": 100}) == 50
        assert level_of({"collections": 41}) == 41
        assert limit_factor(65) == pytest.approx(0.85)


def test_amounts_follow_the_display_currency_at_the_rate_of_the_year(db, tmp_path):
    events = run(db, tmp_path, "what is our credit line?", currency="USD")

    line = done(events)["simulator"]["summary"]
    # 250,000 EUR at the 2026 average of 1.162858 dollars per euro.
    assert line == "Working-capital line of 290,714 USD at 7.0% APR, -58,143 USD on last month."

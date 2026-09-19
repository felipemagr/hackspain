import duckdb
import pytest

from xray.agents.base import ScoreSnapshot
from xray.agents.fleet import (
    AGENTS,
    LIMIT_CURVE,
    MIN_COMPOUND,
    AgentContext,
    Call,
    ChatRequest,
    ChatTurn,
    direct,
    level_of,
    limit_factor,
    pending_request,
    run_chat,
    untraced_figures,
)
from xray.scoring import offer
from xray.scoring.rules import RULES_FILE, load_rules, update_rule
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


def run(
    db, tmp_path, message: str, currency: str = "EUR", history: list[dict] | None = None
) -> list[dict]:
    request = ChatRequest(message=message, month=MONTH, currency=currency, history=history or [])
    return list(run_chat(request, db, no_keys(tmp_path)))


def answer(events: list[dict]) -> str:
    return "".join(e["text"] for e in events if e["type"] == "token")


def done(events: list[dict]) -> dict[str, dict]:
    return {e["id"]: e for e in events if e["type"] == "agent" and e["status"] == "done"}


def steps_of(events: list[dict], agent_id: str) -> list[dict]:
    runs = {e["run"] for e in events if e["type"] == "agent" and e["id"] == agent_id}
    return [e for e in events if e["type"] == "step" and e["run"] in runs]


def test_chat_without_a_model_plans_by_rules_and_answers_from_the_reports(db, tmp_path):
    events = run(db, tmp_path, "  Is g1 on a bump or a fall?  ")

    assert [e["type"] for e in events][:2] == ["planning", "plan"]
    assert events[1]["agents"] == [
        {"run": "1", "id": "scorecard", "reason": "", "target": "g1, 2026-03"}
    ]
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
    events = run(db, tmp_path, "why did the score of g1 move?")

    steps = steps_of(events, "scorecard")
    assert [(s["tool"], s["status"]) for s in steps] == [
        (tool, status)
        for tool in ("pillars_at", "drivers_window", "own_history_rank", "alerts_for")
        for status in ("running", "done")
    ]
    assert steps[1]["output"] == "level 68, bending, 1 of 5 pillars"


def test_a_question_that_names_no_group_reads_the_portfolio(db, tmp_path):
    events = run(db, tmp_path, "how is the portfolio doing?")

    assert [a["id"] for a in events[1]["agents"]] == ["query"]
    query = done(events)["query"]
    assert query["summary"] == "1 row of state, groups, average_level."
    assert query["findings"] == ["state bending, groups 1, average_level 68"]
    assert events[-2]["untraced"] == []


def test_a_question_on_collecting_reads_the_invoices_and_drafts_who_to_chase(db, tmp_path):
    events = run(db, tmp_path, "which customers of g1 should we chase?")

    assert [a["id"] for a in events[1]["agents"]] == ["scorecard", "ledger"]
    ledger = done(events)["ledger"]
    assert ledger["summary"] == (
        "Customer 1 is 60% of billing and the top five are 60%. "
        "40,000 EUR is overdue across 1 customers."
    )
    assert "Customer 2: under 1% of billing, pays 1 day late, payer score 99" in ledger["findings"]
    # The rules narrowed the ledger to invoices: cash and debt were not asked for.
    assert not [e for e in events if e["type"] == "step" and e["tool"] == "cash_profile"]
    suggestion = next(e for e in events if e["type"] == "suggestion")
    assert suggestion["title"] == "Chase Customer 1 this week"


def test_investor_lens_screens_the_group_and_sizes_its_debt_capacity(db, tmp_path):
    events = run(db, tmp_path, "would a search fund buy g1?")

    assert "fails it on: margin 9%, under 15%, state bending" in done(events)["peers"]["summary"]
    # 1.2m revenue at a 9% margin is 108,000 of cash: at 1.5x cover it carries 72,000 of debt
    # service against 77,143 today, so there is no headroom.
    assert any("carries 0 EUR more debt service" in f for f in done(events)["ledger"]["findings"])
    assert not [e for e in events if e["type"] == "suggestion"]


def test_a_group_named_in_the_question_is_compared_at_the_same_month(db, tmp_path):
    db.sql(
        f"""insert into scores values
        ('g2', '{MONTH}', 80, 1, 'healthy', 'healthy', 60, 0.1, 2, null, 1.6, 9)"""
    )
    db.sql(f"insert into drivers values ('g2', '{MONTH}', 'collections', 75, 0, 3)")

    events = run(db, tmp_path, "how does g1 look next to g2 in 2026, or g9?")

    peers = done(events)["peers"]
    assert "g2 is at level 80, healthy, +1.0 points a month, against 68 here." in peers["summary"]
    assert "collections: 41 here, 75 at g2" in peers["findings"]


def test_a_request_to_be_told_becomes_rules_in_the_book(db, tmp_path):
    events = run(
        db,
        tmp_path,
        "Email cfo@example.com when g1 starts falling, severity 20 or more, and slack me "
        "every move",
    )

    assert [a["id"] for a in events[1]["agents"]] == ["scorecard", "notifier"]
    steps = steps_of(events, "notifier")
    assert [s["tool"] for s in steps if s["status"] == "done"] == [
        "rules.list",
        "rules.parse",
        "rules.add",
        "rules.add",
    ]
    assert done(events)["notifier"]["summary"] == (
        "Saved rule 1: Email to cfo@example.com gets critical alerts on g1, severity 20 or more. "
        "Saved rule 2: Slack gets every alert on any group. 2 rules in force."
    )
    saved = load_rules(tmp_path / RULES_FILE)
    assert [(r.channel, r.email_to, r.min_urgency, r.min_severity, r.groups) for r in saved] == [
        ("email", "cfo@example.com", "critical", 20.0, ["g1"]),
        ("slack", None, "info", None, []),
    ]

    # Asking what is set lists the book and adds nothing.
    events = run(db, tmp_path, "which alert rules are in place?")
    assert done(events)["notifier"]["summary"] == "2 rules in force."
    assert len(load_rules(tmp_path / RULES_FILE)) == 2

    # Asking again for a rule already in force keeps the one copy.
    events = run(db, tmp_path, "slack me every move")
    assert done(events)["notifier"]["summary"] == (
        "Already in force as rule 2: Slack gets every alert on any group. Nothing added. "
        "2 rules in force."
    )
    assert len(load_rules(tmp_path / RULES_FILE)) == 2

    # Asking for a rule that was switched off in the alarms panel switches it back on.
    update_rule(tmp_path / RULES_FILE, 2, {"enabled": False})
    events = run(db, tmp_path, "slack me every move")
    assert done(events)["notifier"]["summary"].startswith(
        "Rule 2 was off and is back on: Slack gets every alert on any group."
    )
    assert [r.enabled for r in load_rules(tmp_path / RULES_FILE)] == [True, True]


def test_the_pending_request_stops_at_the_last_answer_that_was_not_a_question():
    turns = [
        ("user", "how is g1 doing?"),
        ("assistant", "g1 is bending."),
        ("user", "alert me when it falls"),
        ("assistant", "It would watch g1 falling. Slack or email? For email, say the address too."),
        ("user", "email"),
        ("assistant", "Which email address?"),
    ]
    history = [ChatTurn(role=role, content=content) for role, content in turns]

    assert pending_request(history) == "alert me when it falls email"
    assert pending_request(history[:2]) == ""


def test_a_request_without_a_channel_waits_for_the_user_to_say_where(db, tmp_path):
    db.sql("insert into groups values ('GROUP_0130', 'GROUP_0130', 'ES', null, false, 1, 0)")
    db.sql(
        f"""insert into scores values
        ('GROUP_0130', '{MONTH}', 72, 1, 'improving', 'healthy', 60, 0.1, 2, null, 1.6, 9)"""
    )
    asked = "Create an alarm whenever the 0130 gets a score above 80"

    events = run(db, tmp_path, asked)

    assert done(events)["notifier"]["summary"] == (
        "Nothing saved yet: a message when GROUP_0130 goes above 80. Slack or email? For email, "
        "say the address too."
    )
    assert load_rules(tmp_path / RULES_FILE) == []
    assert "Slack or email?" in answer(events)

    # The one-word answer picks the channel; email still needs an address.
    history = [{"role": "user", "content": asked}, {"role": "assistant", "content": answer(events)}]
    events = run(db, tmp_path, "email", history=history)

    assert done(events)["notifier"]["summary"] == (
        "Nothing saved yet: a message when GROUP_0130 goes above 80. Which email address?"
    )
    assert load_rules(tmp_path / RULES_FILE) == []

    # The address completes the request from the two turns before.
    history += [
        {"role": "user", "content": "email"},
        {"role": "assistant", "content": answer(events)},
    ]
    events = run(db, tmp_path, "ugarte.p711@gmail.com", history=history)

    (rule,) = load_rules(tmp_path / RULES_FILE)
    assert (rule.channel, rule.email_to) == ("email", "ugarte.p711@gmail.com")
    assert (rule.level_above, rule.groups) == (80, ["GROUP_0130"])
    assert done(events)["notifier"]["summary"].startswith(
        "Saved rule 1: Email to ugarte.p711@gmail.com gets a message when GROUP_0130 goes above 80."
    )


class TestQuery:
    def ask(self, db, tmp_path, query: str) -> tuple[list[dict], dict]:
        steps: list[dict] = []
        call = Call(tool="query", query=query)
        snapshot = ScoreSnapshot(group_id="", month="2026-03", level=0)
        ctx = AgentContext(
            "1", call, ChatRequest(message="?", month=MONTH), snapshot, db, no_keys(tmp_path),
            None, False, steps.append,
        )  # fmt: skip
        return steps, ctx

    def test_rows_come_back_as_text_the_figure_check_can_read(self, db, tmp_path):
        _, ctx = self.ask(db, tmp_path, "select name, overdue_eur from payers order by 2 desc;")

        report = AGENTS["query"](ctx)

        assert report.findings[0] == "name Customer 1, overdue_eur 40,000"
        assert untraced_figures("Customer 1 owes 40,000 EUR.", "\n".join(report.findings)) == []

    @pytest.mark.parametrize(
        "query", ["drop table scores", "select 1; drop table scores", "create table t as select 1"]
    )
    def test_anything_but_one_select_is_refused(self, db, tmp_path, query):
        steps, ctx = self.ask(db, tmp_path, query)

        with pytest.raises(ValueError, match="Only one SELECT"):
            AGENTS["query"](ctx)

        assert steps[-1]["status"] == "failed"
        assert db.sql("select count(*) from scores").fetchone() == (2,)


class TestDirector:
    def move(self, db, llm_answer: str | Exception, message: str = "why?", results=None):
        class FakeLLM:
            def complete(self, system, user):
                if isinstance(llm_answer, Exception):
                    raise llm_answer
                return llm_answer

        request = ChatRequest(message=message, month=MONTH)
        return direct(request, "- scores: level double", results or [], FakeLLM(), db)

    def test_keeps_the_calls_the_fleet_can_run(self, db):
        move = self.move(
            db,
            '{"lens": "lender", "calls": [{"tool": "made_up"}, {"tool": "query"},'
            ' {"tool": "market", "group_id": "g1"},'
            ' {"tool": "ledger", "group_id": "g1", "month": "2026-02",'
            ' "tools": ["cash_profile", "made_up"], "what_if": {"made_up": 5}}]}',
        )

        assert move.lens == "lender"
        assert [call.model_dump(exclude_defaults=True) for call in move.calls] == [
            {"tool": "ledger", "group_id": "g1", "month": "2026-02-01", "tools": ["cash_profile"]}
        ]

    def test_an_agent_call_without_a_month_reads_the_month_on_screen(self, db):
        move = self.move(db, '{"calls": [{"tool": "scorecard", "group_id": "g1"}]}')

        assert move.calls[0].month == "2026-03-01"

    def test_spells_ids_as_the_tables_do_and_never_reads_a_later_month(self, db):
        move = self.move(
            db,
            '{"calls": [{"tool": "peers", "group_id": " G1", "compare": "g9", "month": "2026-09"},'
            ' {"tool": "scorecard", "group_id": "g1", "month": "March 2026"}]}',
        )

        assert [(c.group_id, c.compare, c.month) for c in move.calls] == [
            ("g1", "g9", "2026-03-01"),
            ("g1", None, "2026-03-01"),
        ]

    def test_reads_a_what_if_written_as_pillar_and_points(self, db):
        move = self.move(
            db,
            '{"calls": [{"tool": "simulator", "group_id": "g1",'
            ' "what_if": {"pillar": "collections", "points": 10}},'
            ' {"tool": "simulator", "group_id": "g1",'
            ' "what_if": [{"pillar": "liquidity", "points": -5}, {"pillar": "made_up"}]}]}',
        )

        assert [c.what_if for c in move.calls] == [{"collections": 10}, {"liquidity": -5}]

    def test_sends_an_unreadable_answer_back_once_with_its_error(self, db):
        asked: list[tuple[str, str]] = []

        class Flaky:
            def complete(self, system, user):
                asked.append((system, user))
                if len(asked) == 1:
                    return "Sure, here is the plan."
                return '{"calls": [{"tool": "scorecard", "group_id": "g1"}]}'

        request = ChatRequest(message="why?", month=MONTH)
        move = direct(request, "- scores: level double", [], Flaky(), db, round_no=2)

        assert [call.tool for call in move.calls] == ["scorecard"]
        assert "Round 2 of 4." in asked[0][1]
        assert "could not be read as a move: No JSON object" in asked[1][1]
        # The director reads each agent's rules along with its tools.
        assert "Rule: Runs only for a real company the user names" in asked[0][0]

    def test_falls_back_to_rules_when_the_model_fails_on_the_first_round(self, db):
        move = self.move(db, RuntimeError("down"), message="Is the sector of g1 moving too?")

        assert [call.tool for call in move.calls] == ["scorecard", "macro"]
        assert move.purpose == "us or the market"

    def test_the_fallback_points_the_agents_at_the_last_scored_month(self, db):
        class Down:
            def complete(self, system, user):
                raise RuntimeError("down")

        request = ChatRequest(message="why did G1 move?", month="2026-05-01")
        move = direct(request, "", [], Down(), db)

        assert [(c.tool, c.group_id, c.month) for c in move.calls] == [
            ("scorecard", "g1", "2026-03-01")
        ]

    def test_stops_when_the_model_fails_after_results_came_back(self, db):
        results = [(Call(tool="query", query="select 1"), "1 row")]

        assert self.move(db, RuntimeError("down"), results=results).calls == []


def test_a_failed_call_goes_back_to_the_director_to_be_corrected(db, tmp_path, monkeypatch):
    asked: list[str] = []

    class FakeLLM:
        def complete(self, system, user):
            asked.append(user)
            query = "select level from scores_typo" if len(asked) == 1 else "select 68 as level"
            return f'{{"final": {str(len(asked) > 1).lower()}, "calls": [{{"tool": "query", "query": "{query}"}}]}}'  # noqa: E501

        def stream(self, system, user):
            yield "Level 68."

    monkeypatch.setattr("xray.agents.fleet.build_llm", lambda *_, **__: FakeLLM())

    events = run(db, tmp_path, "what is the level?")

    outcomes = [(e["run"], e["status"]) for e in events if e["type"] == "agent"]
    assert outcomes == [("1", "failed"), ("2", "done")]
    assert "failed: Catalog Error" in asked[1]
    assert events[-2]["untraced"] == []


@pytest.mark.parametrize(
    ("group_id", "month", "error"),
    [
        ("g7", MONTH, "No group g7 in the portfolio: check the id."),
        (
            "g1",
            "2026-05-01",
            "No score for group g1 in 2026-05: its last scored month before that is 2026-03.",
        ),
        (
            "g1",
            "2025-06-01",
            "No score for group g1 in 2025-06: its first scored month is 2025-09, after the "
            "month on screen.",
        ),
    ],
)
def test_an_agent_pointed_at_an_unscored_month_fails_naming_the_month_to_use(
    db, tmp_path, monkeypatch, group_id, month, error
):
    class FakeLLM:
        def complete(self, system, user):
            if "failed:" in user:
                return '{"calls": []}'
            call = f'{{"tool": "scorecard", "group_id": "{group_id}"}}'
            return f'{{"final": true, "calls": [{call}]}}'

        def stream(self, system, user):
            yield "Nothing."

    monkeypatch.setattr("xray.agents.fleet.build_llm", lambda *_, **__: FakeLLM())

    request = ChatRequest(message=f"how is {group_id} doing?", month=month)
    events = list(run_chat(request, db, no_keys(tmp_path)))

    failed = next(e for e in events if e["type"] == "agent")
    assert failed["error"] == error
    assert events[-1]["type"] == "done"


def test_a_final_round_with_a_failed_call_gets_another_to_correct_it(db, tmp_path, monkeypatch):
    class FakeLLM:
        def complete(self, system, user):
            # The director reads the month off the error and re-points the call there.
            month = '"2026-03-01"' if "last scored month before that is 2026-03" in user else "null"
            return f'{{"final": true, "calls": [{{"tool": "scorecard", "group_id": "g1", "month": {month}}}]}}'  # noqa: E501

        def stream(self, system, user):
            yield "Level 68 in 2026-03."

    monkeypatch.setattr("xray.agents.fleet.build_llm", lambda *_, **__: FakeLLM())

    request = ChatRequest(message="how is g1 doing?", month="2026-05-01")
    events = list(run_chat(request, db, no_keys(tmp_path)))

    outcomes = [(e["run"], e["status"]) for e in events if e["type"] == "agent"]
    assert outcomes == [("1", "failed"), ("2", "done")]
    assert [p["agents"][0]["target"] for p in events if p["type"] == "plan"] == [
        "g1, 2026-05",
        "g1, 2026-03",
    ]


def test_a_comparison_with_an_unscored_group_fails_naming_it(db, tmp_path):
    call = Call(tool="peers", group_id="g1", month="2026-03-01", compare="g9", tools=["compare"])
    snapshot = ScoreSnapshot(group_id="g1", month="2026-03", level=68)
    ctx = AgentContext(
        "1", call, ChatRequest(message="?", month=MONTH), snapshot, db, no_keys(tmp_path),
        None, True, lambda _: None,
    )  # fmt: skip

    with pytest.raises(ValueError, match="No score for group g9 in 2026-03 to compare with."):
        AGENTS["peers"](ctx)


def test_the_ledger_says_when_a_group_has_no_invoices_to_read(db, tmp_path):
    call = Call(tool="ledger", group_id="g1", month="2026-03-01", tools=["overdue_ranked"])
    snapshot = ScoreSnapshot(group_id="g1", month="2026-03", level=68)
    ctx = AgentContext(
        "1", call, ChatRequest(message="?", month=MONTH), snapshot, db, no_keys(tmp_path),
        None, False, lambda _: None,
    )  # fmt: skip

    report = AGENTS["ledger"](ctx)

    assert report.summary.startswith("g1 has no ERP connected, so there are no invoices")


class TestFigures:
    def test_a_figure_traces_at_the_precision_it_was_written_with(self):
        source = "Level 68.4, line of 250,000 EUR at 7.0% APR, 3 alerts in 2026-03"

        assert untraced_figures("Level 68, a line of 250,000 EUR, 3 alerts.", source) == []
        assert untraced_figures("Level 70 and 1.2 million EUR.", source) == ["70", "1.2"]
        # A month is a name, not a figure, even when the source never spells it.
        assert untraced_figures("Level 68 in 2025-11, alert on 2025-11-01.", source) == []

    def test_a_thought_with_a_new_figure_never_leads_the_report(self, db, tmp_path):
        class Inventive:
            def complete(self, system, user):
                return "Customer 1 owes 99,999 EUR."

        call = Call(tool="ledger", group_id="g1", month="2026-03-01", why="who owes the most?")
        request = ChatRequest(message="who owes?", month=MONTH)
        snapshot = ScoreSnapshot(group_id="g1", month="2026-03", level=68)
        steps: list[dict] = []
        ctx = AgentContext(
            "1", call, request, snapshot, db, no_keys(tmp_path), Inventive(), True, steps.append
        )

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
    events = run(db, tmp_path, "what is the credit line of g1?", currency="USD")

    line = done(events)["simulator"]["summary"]
    # 250,000 EUR at the 2026 average of 1.162858 dollars per euro.
    assert line == "Working-capital line of 290,714 USD at 7.0% APR, -58,143 USD on last month."

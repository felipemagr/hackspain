import duckdb
import pytest

from xray.agents.base import ScoreSnapshot
from xray.agents.fleet import ChatRequest, make_plan, run_chat
from xray.settings import Settings

MONTH = "2026-03-01 00:00:00"


@pytest.fixture
def db():
    """One group, bending: level 68 from 80, payment discipline dropped, one alert, one offer."""
    con = duckdb.connect()
    con.sql("create table groups (group_id text, name text, country text, sector text)")
    con.sql("insert into groups values ('g1', 'Example Corp', 'ES', 'Retail')")
    con.sql(
        """create table scores (group_id text, month timestamp, level double, trend double,
        state text, tier text, buffer_days double, operating_margin double,
        ap_days_beyond_terms double, ar_days_beyond_terms double, dscr double)"""
    )
    con.sql(
        f"""insert into scores values
        ('g1', '{MONTH}', 68, -2, 'bending', 'coping', 40, 0.08, 21, null, 1.4),
        ('g1', '2025-09-01', 80, 0, 'healthy', 'healthy', 60, 0.1, 2, null, 1.6)"""
    )
    con.sql(
        "create table drivers (group_id text, month timestamp, pillar text, score double,"
        " delta_score double)"
    )
    con.sql(
        f"""insert into drivers values ('g1', '{MONTH}', 'payment_discipline', 41, -15),
        ('g1', '{MONTH}', 'collections', null, null)"""
    )
    con.sql(
        """create table alerts (group_id text, month timestamp, state_from text, state_to text,
        onset_month timestamp, level_at_onset double, level_at_alert double, driver_1 text,
        driver_2 text, anticipation_months double)"""
    )
    con.sql(
        f"""insert into alerts values ('g1', '{MONTH}', 'healthy', 'bending', '2025-12-01',
        80, 68, 'payment_discipline', null, 3)"""
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
        ('g1', '{MONTH}', 1, 'payment_discipline', 'Pay the oldest supplier invoices.', 1.5)"""
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


def test_chat_without_a_model_runs_the_data_agents_and_answers_from_them(db, tmp_path):
    request = ChatRequest(message="  Is this a bump or a fall?  ", group_id="g1", month=MONTH)

    events = list(run_chat(request, db, no_keys(tmp_path)))

    assert [e["type"] for e in events][:2] == ["planning", "plan"]
    assert [a["id"] for a in events[1]["agents"]] == ["score", "monitor", "credit"]
    done = {e["id"]: e for e in events if e["type"] == "agent" and e["status"] == "done"}
    assert done["score"]["summary"].startswith("Level 68, bending, -2.0 points a month")
    assert "It was 80 six months earlier." in done["score"]["summary"]
    assert done["score"]["findings"] == [
        "payment discipline 41 (-15 this month): paying 21 days beyond terms"
    ]
    assert "from healthy to bending" in done["monitor"]["findings"][0]
    assert "3 months before the tier changed" in done["monitor"]["findings"][0]
    assert done["credit"]["summary"] == (
        "Working-capital line of 250,000 EUR at 7.0% APR, -50,000 EUR on last month."
    )
    answer = "".join(e["text"] for e in events if e["type"] == "token")
    assert "Level 68" in answer and "250,000" in answer
    assert events[-1]["type"] == "done"


def test_chat_reports_an_unknown_group(db, tmp_path):
    request = ChatRequest(message="hi", group_id="nope", month=MONTH)

    events = list(run_chat(request, db, no_keys(tmp_path)))

    assert [e["type"] for e in events] == ["error"]


class TestPlanner:
    def ask(self, llm_answer: str | Exception, message: str = "why?"):
        class FakeLLM:
            def complete(self, system, user):
                if isinstance(llm_answer, Exception):
                    raise llm_answer
                return llm_answer

        snapshot = ScoreSnapshot(group_id="g1", month="2026-03", level=68, name="Example Corp")
        request = ChatRequest(message=message, group_id="g1", month=MONTH)
        return make_plan(request, snapshot, FakeLLM())

    def test_keeps_known_agents_in_roster_order_and_always_adds_score(self):
        plan = self.ask('{"agents": ["peers", "made_up", "credit"], "company": "Cabify"}')

        assert plan.agents == ["score", "credit", "peers"]
        assert plan.company == "Cabify"

    def test_falls_back_to_rules_when_the_model_fails(self):
        plan = self.ask(RuntimeError("down"), message="Is the sector moving too?")

        assert plan.agents == ["score", "monitor", "credit", "sector"]

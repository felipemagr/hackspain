import httpx
import pytest

from xray.agents import AgentReport, Orchestrator, ScoreSnapshot
from xray.agents.narrator import NarratorAgent
from xray.agents.tools import tavily


@pytest.fixture
def bending_group() -> ScoreSnapshot:
    """Healthy level, but payment discipline has just dropped below the line."""
    return ScoreSnapshot(
        group_id="g1",
        name="Example Corp",
        month="2026-03",
        country="ES",
        level=68.0,
        pillars={"liquidity": 72.0, "payment_discipline": 41.0, "debt_burden": 30.0},
        deltas={"liquidity": -2.0, "payment_discipline": -15.0},
    )


class TestNarrator:
    def test_ranks_weak_pillars_worst_first(self, bending_group):
        report = NarratorAgent().run(bending_group)

        assert "debt_burden" in report.summary
        assert report.findings == [
            "debt_burden at 30, +0 since last month",
            "payment_discipline at 41, -15 since last month",
        ]

    def test_no_findings_when_every_pillar_is_fine(self, bending_group):
        snapshot = bending_group.model_copy(update={"pillars": {"liquidity": 80.0}})
        assert NarratorAgent().run(snapshot).findings == []


def test_orchestrator_returns_one_report_per_agent_in_order(bending_group):
    class Echo:
        def __init__(self, name):
            self.name = name

        def run(self, snapshot):
            return AgentReport(agent=self.name, summary=snapshot.group_id)

    reports = Orchestrator([Echo("a"), Echo("b")]).run(bending_group)
    assert [r.agent for r in reports] == ["a", "b"]


def test_tavily_search_parses_hits(monkeypatch):
    def fake_post(url, **kwargs):
        assert kwargs["json"]["query"] == "Example Corp company news"
        return httpx.Response(
            200,
            json={"results": [{"title": "Hit", "url": "https://example.com", "content": "..."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(tavily.httpx, "post", fake_post)
    results = tavily.search("Example Corp company news", api_key="k")
    assert [r.url for r in results] == ["https://example.com"]

import contextlib
from datetime import timedelta

import httpx
import pytest

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.cache import JsonCache
from xray.agents.context_retrieval import ContextRetrievalAgent, Extraction
from xray.agents.llm import OpenAICompatibleLLM, complete_json
from xray.agents.narrator import NarratorAgent
from xray.agents.orchestrator import Orchestrator
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


def json_response(url: str, payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


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


class TestContextRetrieval:
    @pytest.fixture
    def tavily_hits(self, monkeypatch):
        """Every query returns the same four hits: two good, one social, one off topic."""
        calls = []

        def hit(title, url, score):
            return {"title": title, "url": url, "content": "", "score": score}

        def fake_post(url, **kwargs):
            calls.append(kwargs["json"])
            results = [
                hit("Example results", "https://a.example", 0.5),
                hit("Example loan", "https://b.example", 0.1 * len(calls)),
                hit("Example post", "https://x.com/p", 0.9),
                hit("Generic page", "https://c.example", 0.9),
            ]
            return json_response(url, {"results": results})

        monkeypatch.setattr(tavily.httpx, "post", fake_post)
        return calls

    def test_retrieve_dedupes_by_url_and_keeps_best_score(self, tavily_hits):
        hits = ContextRetrievalAgent("key", None).retrieve("Example Corp")

        assert [h.url for h in hits] == ["https://a.example", "https://b.example"]
        assert hits[1].score == pytest.approx(0.3)
        assert all("Example Corp" in call["query"] for call in tavily_hits)

    def test_run_without_model_returns_raw_hits(self, tavily_hits, bending_group):
        report = ContextRetrievalAgent("key", None).run(bending_group)

        assert report.findings == ["Example results", "Example loan"]
        assert report.sources == ["https://a.example", "https://b.example"]

    def test_second_run_is_served_from_cache(self, tavily_hits, bending_group, tmp_path):
        agent = ContextRetrievalAgent("key", None, JsonCache(tmp_path, timedelta(days=1)))

        first = agent.run(bending_group)
        calls_after_first = len(tavily_hits)
        second = agent.run(bending_group)

        assert second == first
        assert len(tavily_hits) == calls_after_first
        agent.run(bending_group, refresh=True)
        assert len(tavily_hits) == 2 * calls_after_first

    def test_run_with_model_extracts_dated_findings(self, tavily_hits, bending_group):
        class FakeLLM:
            def complete(self, system, user):
                assert "Example Corp" in user
                assert "tier: other, published: unknown" in user
                return (
                    '```json\n{"summary": "Turned a profit.", "findings": [{"fact": "Net profit'
                    ' of 1m in 2025", "period": "2025", "published": "2026-03-30",'
                    ' "direction": "helps", "source": "https://a.example"}]}\n```'
                )

        report = ContextRetrievalAgent("key", FakeLLM()).run(bending_group)

        assert report.summary == "Turned a profit."
        assert report.findings == ["Net profit of 1m in 2025 [2025, seen 2026-03-30, helps]"]
        assert report.sources == ["https://a.example"]

    def test_skips_without_name(self, bending_group):
        snapshot = bending_group.model_copy(update={"name": None})
        assert ContextRetrievalAgent("key", None).run(snapshot).findings == []


def test_openai_compatible_llm_joins_streamed_content(monkeypatch):
    lines = [
        'data: {"choices": [{"delta": {"role": "assistant", "reasoning_content": "hm"}}]}',
        'data: {"choices": [{"delta": {"content": "hel"}}]}',
        "",
        'data: {"choices": [{"delta": {"content": "lo"}}]}',
        'data: {"choices": [], "usage": {}}',
        "data: [DONE]",
    ]

    def fake_stream(method, url, **kwargs):
        assert url == "https://llm.example/v1/chat/completions"
        assert kwargs["json"]["messages"][0] == {"role": "system", "content": "sys"}
        request = httpx.Request(method, url)
        return contextlib.nullcontext(httpx.Response(200, text="\n".join(lines), request=request))

    monkeypatch.setattr(httpx, "stream", fake_stream)
    llm = OpenAICompatibleLLM(api_key="k", model="m", base_url="https://llm.example/v1/")
    assert llm.complete("sys", "usr") == "hello"


class TestCompleteJson:
    @pytest.mark.parametrize(
        "answer",
        [
            '{"summary": "fine"}',
            '```json\n{"summary": "fine"}\n```',
            'Here is the read:\n{"summary": "fine"}\nLet me know if you need more.',
        ],
    )
    def test_reads_the_object_out_of_fences_and_prose(self, answer):
        class Wordy:
            def complete(self, system, user):
                return answer

        assert complete_json(Wordy(), "sys", "usr", Extraction).summary == "fine"

    def test_an_answer_without_an_object_names_what_came_back(self):
        class Chatty:
            def complete(self, system, user):
                return "I cannot do that."

        with pytest.raises(ValueError, match="No JSON object in the answer: 'I cannot do that.'"):
            complete_json(Chatty(), "sys", "usr", Extraction)

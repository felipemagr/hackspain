from datetime import timedelta

import httpx
import pytest

from xray.agents.base import ScoreSnapshot
from xray.agents.cache import JsonCache
from xray.agents.peers import PeersAgent
from xray.agents.tools import exa


@pytest.fixture
def snapshot() -> ScoreSnapshot:
    return ScoreSnapshot(
        group_id="g1", name="Example Corp", month="2026-03", level=68.0, deltas={"liquidity": -9.0}
    )


@pytest.fixture
def exa_calls(monkeypatch):
    """Every search returns one dated article and one social post."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        results = [
            {"title": "Rival cuts staff", "url": "https://news.example/rival",
             "publishedDate": "2026-02-10T00:00:00.000Z", "text": "Rival lays off 200."},
            {"title": "Post", "url": "https://x.com/p", "text": ""},
        ]  # fmt: skip
        return httpx.Response(200, json={"results": results}, request=httpx.Request("POST", url))

    monkeypatch.setattr(exa.httpx, "post", fake_post)
    return calls


class FakeLLM:
    def complete(self, system, user):
        if "Candidates:" in user:
            return '{"sector": "ride hailing", "peers": ["Rival", "Other", "C", "D", "E"]}'
        assert "published: 2026-02-10" in user
        assert "x.com" not in user
        assert "liquidity -9" in user
        return (
            '```json\n{"sector_direction": "deteriorating", "summary": "Peers are cutting too.",'
            ' "findings": [{"peer": "Rival", "fact": "Laid off 200 in Q1 2026",'
            ' "published": "2026-02-10", "direction": "hurts",'
            ' "source": "https://news.example/rival"}]}\n```'
        )


def test_run_finds_peers_then_reads_their_news(exa_calls, snapshot):
    report = PeersAgent("key", FakeLLM()).run(snapshot)

    assert report.summary == "ride hailing, sector deteriorating. Peers are cutting too."
    assert report.findings == ["Rival: Laid off 200 in Q1 2026 [seen 2026-02-10, hurts]"]
    assert report.sources == ["https://news.example/rival"]
    assert exa_calls[0]["category"] == "company"
    # One company search, then one news search for each of the four peers kept.
    assert [call.get("category") for call in exa_calls[1:]] == ["news"] * 4


def test_second_run_is_served_from_cache(exa_calls, snapshot, tmp_path):
    agent = PeersAgent("key", FakeLLM(), JsonCache(tmp_path, timedelta(days=1)))

    first = agent.run(snapshot)
    calls_after_first = len(exa_calls)

    assert agent.run(snapshot) == first
    assert len(exa_calls) == calls_after_first


def test_skips_without_key_or_model(snapshot):
    assert PeersAgent(None, FakeLLM()).run(snapshot).findings == []
    assert PeersAgent("key", None).run(snapshot).findings == []

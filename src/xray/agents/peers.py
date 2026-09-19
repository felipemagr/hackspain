"""Agents: is the company moving alone or with its sector?

`PeersAgent` needs a real company: it finds its competitors and reads their news.
`SectorAgent` needs only a sector and a country, so it works on any group.

QA on a real company with: make peers NAME="Cabify"
"""

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from pydantic import BaseModel, Field

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.cache import JsonCache
from xray.agents.llm import LLM, build_llm, complete_json
from xray.agents.sources import is_social, published_on
from xray.agents.tools import exa
from xray.agents.tools.exa import ExaResult
from xray.settings import Settings, get_settings

logger = logging.getLogger(__name__)

MAX_PEERS = 4
PEER_CANDIDATES = 8
NEWS_PER_PEER = 3
NEWS_WINDOW_DAYS = 540
SNIPPET_CHARS = 600
SECTOR_NEWS = 8
COUNTRY_NAMES = {"ES": "Spain", "PT": "Portugal", "FR": "France", "IT": "Italy"}

PEERS_PROMPT = """You are given web pages about the competitive landscape of a target company.
Pick its direct competitors as the pages name them: same business, overlapping markets, the
ones named most often first. Drop the target itself, its subsidiaries, suppliers and the
sites that publish the comparisons. Only use names that appear in the pages.

Answer with JSON only:
{"sector": "the sector in three or four words", "peers": ["Company name", ...]}
At most {max_peers} peers, best known first. Use the short trade name."""

SECTOR_PROMPT = """You read recent news about the competitors of a company, for a financial
health monitor used by a CFO and their lenders. The question is whether the company's score
is moving with its sector or on its own.

Keep only facts about the peers' financial health or about pressure on the whole sector:
results, margins, debt, financing, insolvency, layoffs, closures, regulation, demand.
Never invent a number that is not in the sources.

Answer with JSON only, no prose around it:
{
  "sector_direction": "improving" | "deteriorating" | "mixed" | "unknown",
  "summary": "two or three sentences: how the peers are doing, and whether the target's
              score move looks sector-wide or specific to the company",
  "findings": [
    {"peer": "company name, or 'sector' for a fact about all of them",
     "fact": "one sentence with the number and the period",
     "published": "YYYY-MM-DD as given for the source, or null",
     "direction": "helps" | "hurts" | "neutral",
     "source": "url"}
  ]
}
Order findings by `published` descending, undated last. Write in English."""


class PeerSet(BaseModel):
    sector: str
    peers: list[str] = Field(default_factory=list)


class PeerFinding(BaseModel):
    peer: str
    fact: str
    published: date | None = None
    direction: str = "neutral"
    source: str | None = None


class SectorRead(BaseModel):
    sector_direction: str = "unknown"
    summary: str
    findings: list[PeerFinding] = Field(default_factory=list)


class PeersAgent:
    name = "peers"

    def __init__(self, exa_api_key: str | None, llm: LLM | None, cache: JsonCache | None = None):
        self.exa_api_key = exa_api_key
        self.llm = llm
        self.cache = cache

    def find_peers(self, snapshot: ScoreSnapshot) -> PeerSet:
        assert self.exa_api_key and self.llm and snapshot.name
        # Exa's `company` category returns look-alike home pages and misses the obvious rivals.
        # Plain search returns the articles that compare the company with them.
        hits = exa.search(
            f"{snapshot.name} competidores principales: empresas rivales en sus mercados",
            self.exa_api_key,
            num_results=PEER_CANDIDATES,
            text_chars=SNIPPET_CHARS,
        )
        user = f"Target company: {snapshot.name}\n\nPages:\n\n" + _blocks(hits)
        system = PEERS_PROMPT.replace("{max_peers}", str(MAX_PEERS))
        peer_set = complete_json(self.llm, system, user, PeerSet)
        peer_set.peers = peer_set.peers[:MAX_PEERS]
        return peer_set

    def peer_news(self, peer_set: PeerSet) -> dict[str, list[ExaResult]]:
        assert self.exa_api_key
        since = date.today() - timedelta(days=NEWS_WINDOW_DAYS)

        def one(peer: str) -> list[ExaResult]:
            hits = exa.search(
                # The sector keeps a common name on the right company: Bolt the ride-hailing
                # firm, not Bolt the checkout fintech.
                f"{peer} ({peer_set.sector}) financial results, debt, layoffs, regulation",
                self.exa_api_key,
                num_results=NEWS_PER_PEER,
                category="news",
                published_after=since,
                text_chars=SNIPPET_CHARS,
            )
            return [hit for hit in hits if not is_social(hit.url)]

        peers = peer_set.peers
        with ThreadPoolExecutor(max_workers=len(peers)) as pool:
            return dict(zip(peers, pool.map(one, peers), strict=True))

    def read_sector(
        self, snapshot: ScoreSnapshot, peer_set: PeerSet, news: dict[str, list[ExaResult]]
    ) -> SectorRead:
        assert self.llm
        moves = ", ".join(f"{pillar} {delta:+.0f}" for pillar, delta in snapshot.deltas.items())
        sections = [f"## {peer}\n\n{_blocks(hits)}" for peer, hits in news.items() if hits]
        user = (
            f"Target: {snapshot.name}, sector: {peer_set.sector}\n"
            f"Score {snapshot.level:.0f}/100 in {snapshot.month}, "
            f"moves since last month: {moves or 'none reported'}\n\n" + "\n\n".join(sections)
        )
        return complete_json(self.llm, SECTOR_PROMPT, user, SectorRead)

    def run(self, snapshot: ScoreSnapshot, refresh: bool = False) -> AgentReport:
        if not self.exa_api_key or not self.llm or not snapshot.name:
            logger.info("Peers skipped for %s: needs a name, Exa and a model", snapshot.group_id)
            return AgentReport(agent=self.name, summary="No peer comparison available.")
        key = f"{snapshot.name} peers"
        if self.cache and not refresh and (cached := self.cache.get(key)):
            return AgentReport.model_validate(cached["report"])
        peer_set = self.find_peers(snapshot)
        if not peer_set.peers:
            return AgentReport(agent=self.name, summary=f"No peers found for {snapshot.name}.")
        news = self.peer_news(peer_set)
        read = self.read_sector(snapshot, peer_set, news)
        report = AgentReport(
            agent=self.name,
            summary=f"{peer_set.sector}, sector {read.sector_direction}. {read.summary}",
            findings=[_line(f) for f in read.findings],
            sources=sorted({f.source for f in read.findings if f.source}),
        )
        if self.cache:
            payload = {
                "sector": peer_set.sector,
                "sector_direction": read.sector_direction,
                "peers": peer_set.peers,
                "report": report.model_dump(),
            }
            self.cache.put(key, payload)
        return report


class SectorAgent:
    """Recent news on the group's sector in its country, read for pressure on financial health."""

    name = "sector"

    def __init__(self, exa_api_key: str | None, llm: LLM | None, cache: JsonCache | None = None):
        self.exa_api_key = exa_api_key
        self.llm = llm
        self.cache = cache

    def run(self, snapshot: ScoreSnapshot, refresh: bool = False) -> AgentReport:
        if not self.exa_api_key or not self.llm or not snapshot.sector:
            return AgentReport(agent=self.name, summary="No sector read available.")
        country = COUNTRY_NAMES.get(snapshot.country or "", snapshot.country or "Europe")
        key = f"sector {snapshot.sector} {country}"
        if self.cache and not refresh and (cached := self.cache.get(key)):
            return AgentReport.model_validate(cached["report"])
        hits = exa.search(
            f"{snapshot.sector} sector in {country}: demand, costs, margins, financing, defaults",
            self.exa_api_key,
            num_results=SECTOR_NEWS,
            category="news",
            published_after=date.today() - timedelta(days=NEWS_WINDOW_DAYS),
            text_chars=SNIPPET_CHARS,
        )
        hits = [hit for hit in hits if not is_social(hit.url)]
        if not hits:
            return AgentReport(agent=self.name, summary=f"No recent news on {snapshot.sector}.")
        moves = ", ".join(f"{pillar} {delta:+.0f}" for pillar, delta in snapshot.deltas.items())
        user = (
            f"Target: {snapshot.name}, sector: {snapshot.sector} in {country}\n"
            f"Score {snapshot.level:.0f}/100 in {snapshot.month}, "
            f"moves since last month: {moves or 'none reported'}\n"
            "The sources are about the sector, not about named peers: use 'sector' as the peer.\n\n"
            + _blocks(hits)
        )
        read = complete_json(self.llm, SECTOR_PROMPT, user, SectorRead)
        report = AgentReport(
            agent=self.name,
            summary=f"{snapshot.sector} in {country}, {read.sector_direction}. {read.summary}",
            findings=[_line(f) for f in read.findings],
            sources=sorted({f.source for f in read.findings if f.source}),
        )
        if self.cache:
            self.cache.put(key, {"report": report.model_dump()})
        return report


def build_agent(settings: Settings) -> PeersAgent:
    cache = JsonCache(settings.serving_dir / "context", timedelta(days=settings.context_ttl_days))
    return PeersAgent(settings.exa_api_key, build_llm(settings), cache)


def build_sector_agent(settings: Settings) -> SectorAgent:
    cache = JsonCache(settings.serving_dir / "context", timedelta(days=settings.context_ttl_days))
    return SectorAgent(settings.exa_api_key, build_llm(settings), cache)


def _blocks(hits: list[ExaResult]) -> str:
    blocks = []
    for i, hit in enumerate(hits, start=1):
        # Exa dates are ISO, which published_on does not parse: it only covers the URL here.
        when = (hit.published_date or "")[:10] or published_on(hit.url, None)
        blocks.append(
            f"[{i}] {hit.title or ''}\n{hit.url}\npublished: {when or 'unknown'}\n{hit.text}"
        )
    return "\n\n".join(blocks)


def _line(finding: PeerFinding) -> str:
    seen = finding.published.isoformat() if finding.published else "undated"
    who = "" if finding.peer.lower() == "sector" else f"{finding.peer}: "
    return f"{who}{finding.fact} [seen {seen}, {finding.direction}]"


def main() -> None:
    """QA entry point: peers for one company name, from cache unless --refresh."""
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="+")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and search again")
    args = parser.parse_args()
    agent = build_agent(get_settings())
    snapshot = ScoreSnapshot(group_id="qa", name=" ".join(args.name), month="2026-09", level=50)
    report = agent.run(snapshot, refresh=args.refresh)
    print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

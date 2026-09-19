"""Agent: is the company moving alone or with its sector? Finds peers on the web and reads them.

QA it on a real company with: make peers NAME="Cabify"
"""

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from pydantic import BaseModel, Field

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.cache import JsonCache
from xray.agents.context_retrieval import _strip_fences
from xray.agents.llm import LLM, build_llm
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

PEERS_PROMPT = """You are given web pages of companies that may compete with a target company.
Pick the direct competitors: same business, overlapping markets. Drop the target itself,
its subsidiaries, directories, marketplaces of reviews and anything that is not a company.

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
        hits = exa.search(
            f"companies that compete with {snapshot.name}, same business and markets",
            self.exa_api_key,
            num_results=PEER_CANDIDATES,
            category="company",
        )
        user = f"Target company: {snapshot.name}\n\nCandidates:\n\n" + _blocks(hits)
        raw = self.llm.complete(PEERS_PROMPT.replace("{max_peers}", str(MAX_PEERS)), user)
        peer_set = PeerSet.model_validate_json(_strip_fences(raw))
        peer_set.peers = peer_set.peers[:MAX_PEERS]
        return peer_set

    def peer_news(self, peers: list[str]) -> dict[str, list[ExaResult]]:
        assert self.exa_api_key
        since = date.today() - timedelta(days=NEWS_WINDOW_DAYS)

        def one(peer: str) -> list[ExaResult]:
            hits = exa.search(
                f"{peer} financial results, debt, layoffs, regulation",
                self.exa_api_key,
                num_results=NEWS_PER_PEER,
                category="news",
                published_after=since,
                text_chars=SNIPPET_CHARS,
            )
            return [hit for hit in hits if not is_social(hit.url)]

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
        return SectorRead.model_validate_json(_strip_fences(self.llm.complete(SECTOR_PROMPT, user)))

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
        news = self.peer_news(peer_set.peers)
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


def build_agent(settings: Settings) -> PeersAgent:
    cache = JsonCache(settings.serving_dir / "context", timedelta(days=settings.context_ttl_days))
    return PeersAgent(settings.exa_api_key, build_llm(settings), cache)


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
    return f"{finding.peer}: {finding.fact} [seen {seen}, {finding.direction}]"


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

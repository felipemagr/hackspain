"""Agent 1: public financial context about a company, retrieved from the web and cached.

QA it on a real company with: make context NAME="Cabify"
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
from xray.agents.sources import TIER_LABELS, is_social, published_on, tier
from xray.agents.tools import tavily
from xray.agents.tools.tavily import Depth, SearchResult, Topic
from xray.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# One query per angle a lender would check: 2 + 1 + 1 credits per company.
# All on `general`: for Spanish companies it finds the financial press and the registry, while
# `news` dates its hits but returns aggregators and job boards. Dates come from the URL instead.
QUERIES: tuple[tuple[str, Topic, Depth], ...] = (
    ('"{name}" resultados ventas ebitda beneficio deuda', "general", "advanced"),
    ('"{name}" financiación préstamo refinanciación concurso de acreedores', "general", "basic"),
    ('"{name}" despidos ERE cierre inversión ampliación contrato', "general", "basic"),
)
MAX_RESULTS_PER_QUERY = 5
MIN_SCORE = 0.2
SNIPPET_CHARS = 700

SYSTEM_PROMPT = """You extract financial facts about a company from web search results,
for a financial health monitor used by a CFO and their lenders.

Keep only facts that could move the company's financial health: revenue, margins,
profit or loss, debt, financing obtained or refinanced, insolvency proceedings,
late payments, layoffs, closures, large contracts won or lost, ownership changes.
Ignore marketing, awards and product launches. Never invent a number that is not
in the sources. Each source carries a trust tier (official, registry, financial
press, other) and a publication date when known: when sources disagree, prefer the
higher tier, then the more recent, and say so.

Answer with JSON only, no prose around it:
{
  "summary": "two or three sentences on the company's financial situation as the sources show it",
  "findings": [
    {"fact": "one sentence with the number and the period",
     "period": "the fiscal period the fact is about, e.g. 2025 or 2025-H1, or null",
     "published": "YYYY-MM-DD as given for the source, or null when the source has no date",
     "direction": "helps" | "hurts" | "neutral",
     "source": "url"}
  ]
}
`published` is when the fact became public, so copy it from the source line, never guess it.
Order findings by `published` descending, undated last. Write in English."""


class Finding(BaseModel):
    fact: str
    period: str | None = None
    published: date | None = None
    direction: str = "neutral"
    source: str | None = None


class Extraction(BaseModel):
    summary: str
    findings: list[Finding] = Field(default_factory=list)


class ContextRetrievalAgent:
    name = "context_retrieval"

    def __init__(self, tavily_api_key: str | None, llm: LLM | None, cache: JsonCache | None = None):
        self.tavily_api_key = tavily_api_key
        self.llm = llm
        self.cache = cache

    def retrieve(self, name: str) -> list[SearchResult]:
        """Every query in QUERIES at once, deduplicated by URL, best score first."""
        assert self.tavily_api_key

        def one(query: tuple[str, Topic, Depth]) -> list[SearchResult]:
            template, topic, depth = query
            return tavily.search(
                template.format(name=name),
                self.tavily_api_key,
                max_results=MAX_RESULTS_PER_QUERY,
                topic=topic,
                search_depth=depth,
            ).results

        with ThreadPoolExecutor(max_workers=len(QUERIES)) as pool:
            batches = list(pool.map(one, QUERIES))
        by_url: dict[str, SearchResult] = {}
        for hit in (hit for batch in batches for hit in batch):
            if hit.score < MIN_SCORE or is_social(hit.url) or not _mentions(hit, name):
                continue
            if hit.url not in by_url or hit.score > by_url[hit.url].score:
                by_url[hit.url] = hit
        return sorted(by_url.values(), key=lambda hit: hit.score, reverse=True)

    def extract(self, name: str, hits: list[SearchResult]) -> Extraction:
        assert self.llm
        blocks = []
        for i, hit in enumerate(hits, start=1):
            when = published_on(hit.url, hit.published_date)
            blocks.append(
                f"[{i}] {hit.title}\n{hit.url}\n"
                f"tier: {TIER_LABELS[tier(hit.url)]}, published: {when or 'unknown'}\n"
                f"{hit.content[:SNIPPET_CHARS]}"
            )
        user = f"Company: {name}\n\nSearch results:\n\n" + "\n\n".join(blocks)
        return complete_json(self.llm, SYSTEM_PROMPT, user, Extraction)

    def run(self, snapshot: ScoreSnapshot, refresh: bool = False) -> AgentReport:
        if not self.tavily_api_key or not snapshot.name:
            logger.info("Context retrieval skipped for %s: no API key or name", snapshot.group_id)
            return AgentReport(agent=self.name, summary="No public context available.")
        if self.cache and not refresh and (cached := self.cache.get(snapshot.name)):
            return AgentReport.model_validate(cached["report"])
        hits = self.retrieve(snapshot.name)
        report = self._report(snapshot.name, hits)
        if self.cache:
            payload = {"hits": [hit.model_dump() for hit in hits], "report": report.model_dump()}
            self.cache.put(snapshot.name, payload)
        return report

    def _report(self, name: str, hits: list[SearchResult]) -> AgentReport:
        if not hits:
            return AgentReport(agent=self.name, summary=f"Nothing public found on {name}.")
        if self.llm is None:
            return AgentReport(
                agent=self.name,
                summary=f"{len(hits)} public sources found for {name}, not read.",
                findings=[hit.title for hit in hits],
                sources=[hit.url for hit in hits],
            )
        extraction = self.extract(name, hits)
        return AgentReport(
            agent=self.name,
            summary=extraction.summary,
            findings=[_line(f) for f in extraction.findings],
            sources=sorted({f.source for f in extraction.findings if f.source}),
        )


def build_agent(settings: Settings) -> ContextRetrievalAgent:
    cache = JsonCache(settings.serving_dir / "context", timedelta(days=settings.context_ttl_days))
    return ContextRetrievalAgent(settings.tavily_api_key, build_llm(settings), cache)


def _mentions(hit: SearchResult, name: str) -> bool:
    """Generic pages rank well on the query's finance words without being about the company."""
    text = f"{hit.title} {hit.content}".lower()
    return any(word in text for word in name.lower().split() if len(word) > 3)


def _line(finding: Finding) -> str:
    seen = finding.published.isoformat() if finding.published else "undated"
    period = finding.period or "period unknown"
    return f"{finding.fact} [{period}, seen {seen}, {finding.direction}]"


def main() -> None:
    """QA entry point: context for one company name, from cache unless --refresh."""
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="+")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and search again")
    args = parser.parse_args()
    name = " ".join(args.name)
    agent = build_agent(get_settings())
    snapshot = ScoreSnapshot(group_id="qa", name=name, month="2026-09", level=50)
    report = agent.run(snapshot, refresh=args.refresh)
    print(json.dumps(report.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

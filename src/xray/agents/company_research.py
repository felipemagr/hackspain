"""Agent 1: public information about the group, found on the web."""

import logging

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.llm import LLM
from xray.agents.tools import tavily

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You research companies for a financial health monitor.
Given search results about a company, list the facts that could move its
financial health: ownership changes, layoffs, new financing, lawsuits, large
contracts won or lost. Cite the source URL for each fact."""


class CompanyResearchAgent:
    name = "company_research"

    def __init__(self, tavily_api_key: str | None, llm: LLM | None = None):
        self.tavily_api_key = tavily_api_key
        self.llm = llm

    def run(self, snapshot: ScoreSnapshot) -> AgentReport:
        if not self.tavily_api_key or not snapshot.name:
            logger.info("Company research skipped for %s: no API key or name", snapshot.group_id)
            return AgentReport(agent=self.name, summary="No public research available.")
        results = tavily.search(f"{snapshot.name} company news", self.tavily_api_key)
        # Stub: returns the raw hits. The LLM pass over them is not wired yet.
        return AgentReport(
            agent=self.name,
            summary=f"{len(results)} public sources found for {snapshot.name}.",
            findings=[result.title for result in results],
            sources=[result.url for result in results],
        )

"""Agent 2: macro context for the group's country at the scored month."""

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.llm import LLM

SYSTEM_PROMPT = """You are a macro analyst. Given a country and a month, describe the
conditions a mid-market company faced then: rates, inflation, credit availability,
sector demand. Say which of them help or hurt liquidity and collections."""


class MacroAgent:
    name = "macro"

    def __init__(self, llm: LLM | None = None):
        self.llm = llm

    def run(self, snapshot: ScoreSnapshot) -> AgentReport:
        # Stub: the data source (historical series or live) is not chosen yet.
        where = snapshot.country or "unknown country"
        return AgentReport(
            agent=self.name,
            summary=f"Macro context for {where} at {snapshot.month} not available yet.",
        )

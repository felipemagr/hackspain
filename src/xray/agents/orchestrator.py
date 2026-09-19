"""Runs the agents in order over one snapshot and collects their reports."""

from collections.abc import Sequence

from xray.agents.base import Agent, AgentReport, ScoreSnapshot
from xray.agents.company_research import CompanyResearchAgent
from xray.agents.macro import MacroAgent
from xray.agents.narrator import NarratorAgent
from xray.settings import Settings


class Orchestrator:
    def __init__(self, agents: Sequence[Agent]):
        self.agents = list(agents)

    def run(self, snapshot: ScoreSnapshot) -> list[AgentReport]:
        return [agent.run(snapshot) for agent in self.agents]


def build_orchestrator(settings: Settings) -> Orchestrator:
    """The default line-up: research, then macro, then the narrative."""
    return Orchestrator(
        [
            CompanyResearchAgent(tavily_api_key=settings.tavily_api_key),
            MacroAgent(),
            NarratorAgent(),
        ]
    )

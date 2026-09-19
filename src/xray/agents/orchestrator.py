"""Runs the agents in order over one snapshot and collects their reports."""

from collections.abc import Sequence

from xray.agents.base import Agent, AgentReport, ScoreSnapshot
from xray.agents.context_retrieval import build_agent as build_context_agent
from xray.agents.llm import build_llm
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
    llm = build_llm(settings)
    return Orchestrator(
        [
            build_context_agent(settings),
            MacroAgent(llm),
            NarratorAgent(llm),
        ]
    )

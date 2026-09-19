"""Agents that read the score and add context around it. None of them recomputes the score.

- company_research: public information about the group, through the Tavily search tool.
- macro: macro context for the group's country at the scored month.
- narrator: where the group is weak, written from the pillar decomposition.

`Orchestrator` runs them in that order over one `ScoreSnapshot`. Every agent is a stub
until we decide to wire a model behind it.
"""

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.orchestrator import Orchestrator, build_orchestrator

__all__ = ["AgentReport", "Orchestrator", "ScoreSnapshot", "build_orchestrator"]

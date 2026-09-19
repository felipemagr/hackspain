"""Contract shared by every agent: what goes in, what comes out."""

from typing import Protocol

from pydantic import BaseModel, Field


class ScoreSnapshot(BaseModel):
    """What the score engine knows about one group at one month.

    Pillars and deltas are keyed by pillar name, on the 0-100 scale of the score.
    """

    group_id: str
    month: str
    level: float
    name: str | None = None
    country: str | None = None
    sector: str | None = None
    pillars: dict[str, float] = Field(default_factory=dict)
    deltas: dict[str, float] = Field(default_factory=dict)


class AgentReport(BaseModel):
    """One agent's contribution, ready to display next to the score."""

    agent: str
    summary: str
    findings: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Agent(Protocol):
    name: str

    def run(self, snapshot: ScoreSnapshot) -> AgentReport: ...

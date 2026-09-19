"""Agent 3: where the group is weak, written from the pillar decomposition."""

from xray.agents.base import AgentReport, ScoreSnapshot
from xray.agents.llm import LLM

WEAK_PILLAR_THRESHOLD = 50.0

SYSTEM_PROMPT = """You explain a financial health score to a CFO. The score is a weighted
mean of pillars, each 0-100. You receive the pillars, their weights and their change
since last month. Name the pillars that drag the score, say what moved and since when,
and never invent a number that is not in the input."""


class NarratorAgent:
    name = "narrator"

    def __init__(self, llm: LLM | None = None):
        self.llm = llm

    def run(self, snapshot: ScoreSnapshot) -> AgentReport:
        # Stub: deterministic ranking of the weak pillars. The prose pass is not wired yet.
        weak = sorted(
            (p for p in snapshot.pillars.items() if p[1] < WEAK_PILLAR_THRESHOLD),
            key=lambda item: item[1],
        )
        findings = [
            f"{pillar} at {value:.0f}, {snapshot.deltas.get(pillar, 0.0):+.0f} since last month"
            for pillar, value in weak
        ]
        summary = (
            f"Level {snapshot.level:.0f}. Weakest pillar: {weak[0][0]}."
            if weak
            else f"Level {snapshot.level:.0f}. No pillar below {WEAK_PILLAR_THRESHOLD:.0f}."
        )
        return AgentReport(agent=self.name, summary=summary, findings=findings)

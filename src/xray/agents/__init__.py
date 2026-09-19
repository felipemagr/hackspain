"""Agents that read the score and add context around it. None of them recomputes the score.

- context_retrieval: public financial context about the group, Tavily search read by the model.
- macro: macro context for the group's country at the scored month.
- narrator: where the group is weak, written from the pillar decomposition.

`Orchestrator` runs them in that order over one `ScoreSnapshot`. The model behind them is
whatever `build_llm` returns; without a key the agents fall back to raw output.
"""

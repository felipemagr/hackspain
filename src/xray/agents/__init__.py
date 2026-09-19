"""Agents that read the score and add context around it. None of them recomputes the score.

- context_retrieval: public financial context about the group, Tavily search read by the model.
- macro: macro context for the group's country at the scored month.
- narrator: where the group is weak, written from the pillar decomposition.
- peers: competitors of a real company and the sector of any group, Exa search read by the model.
- fleet: the chat. A planner guides generic agents over the scorecard, a writer answers and
  every figure is checked against what the tools returned.
- notifier: reads "tell me on Slack when a group starts falling" into a rule of the alert book.

`Orchestrator` runs them in that order over one `ScoreSnapshot`. The model behind them is
whatever `build_llm` returns; without a key the agents fall back to raw output.
"""

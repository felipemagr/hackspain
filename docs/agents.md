# Agents around the score

The score engine produces a number and its pillar decomposition. The agents in
`src/xray/agents/` add context around that number. They never recompute it.

| Agent | Module | Reads | Produces |
|---|---|---|---|
| Company research | `company_research.py` | group name, Tavily web search | public facts that could move the score, with source URLs |
| Macro | `macro.py` | country, month | conditions that help or hurt liquidity and collections |
| Narrator | `narrator.py` | level, pillars, month-on-month deltas | which pillars drag the score, what moved and since when |

## Contract

Every agent implements `run(snapshot: ScoreSnapshot) -> AgentReport` (`base.py`).
`ScoreSnapshot` is what the engine knows about one group at one month. `AgentReport`
is one summary, a list of findings and a list of sources, ready for the API and the demo.

`Orchestrator` (`orchestrator.py`) runs the agents in order and returns one report each.
`build_orchestrator(settings)` gives the default line-up.

## Tools

One module per external service under `tools/`. `tavily.py` wraps the Tavily search
endpoint over `httpx`, keyed by `XRAY_TAVILY_API_KEY`.

## What is a stub

All three agents run today without a model: research returns raw search hits, macro
returns a placeholder, the narrator ranks weak pillars deterministically. The model
seam is the `LLM` protocol in `llm.py`; each agent holds an optional `llm` and the
`SYSTEM_PROMPT` it will use. Provider, data source for macro and prompt wording are
open decisions.

# Agents around the score

The score engine produces a number and its pillar decomposition. The agents in
`src/xray/agents/` add context around that number. They never recompute it.

| Agent | Module | Reads | Produces |
|---|---|---|---|
| Context retrieval | `context_retrieval.py` | group name, Tavily web search, model | financial facts that could move the score, with fiscal period, publication date, direction and source URL |
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
endpoint over `httpx`, keyed by `TAVILY_API_KEY`. `sources.py` ranks domains by trust and reads
publication dates; `cache.py` is the JSON cache with a TTL.

## Model

`llm.py` holds the `LLM` protocol and `OpenAICompatibleLLM`, a chat-completions client
over httpx. `build_llm(settings)` points it at Helmcode (`HELMCODE_API_KEY`,
`XRAY_LLM_MODEL`, default `deepseek-v4-flash`) or returns None when there is no key.

## State of each agent

- Context retrieval works end to end and is cached. Pipeline, source tiers, dates, cache and what
  was tried and dropped: `docs/architecture.md` section 8. QA: `make context NAME="Cabify"`,
  add `REFRESH=1` to search again. Cached reports live in `data/serving/context/`.
- Macro returns a placeholder. Data source not chosen.
- Narrator ranks weak pillars deterministically. The prose pass is not wired.

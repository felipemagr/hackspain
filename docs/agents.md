# Agents around the score

The score engine produces a number and its pillar decomposition. The agents in
`src/xray/agents/` add context around that number. They never recompute it.

| Agent | Module | Reads | Produces |
|---|---|---|---|
| Context retrieval | `context_retrieval.py` | group name, Tavily web search, model | financial facts that could move the score, with fiscal period, publication date, direction and source URL |
| Peers | `peers.py` | group name, Exa semantic search, model | whether the score is moving with the sector or alone: competitors named by the articles Exa finds on the company's rivals, their recent news, a sector direction and dated facts per peer |
| Macro | `macro.py` | country, month | conditions that help or hurt liquidity and collections |
| Narrator | `narrator.py` | level, pillars, month-on-month deltas | which pillars drag the score, what moved and since when |

## Contract

Every agent implements `run(snapshot: ScoreSnapshot) -> AgentReport` (`base.py`).
`ScoreSnapshot` is what the engine knows about one group at one month. `AgentReport`
is one summary, a list of findings and a list of sources, ready for the API and the demo.

`Orchestrator` (`orchestrator.py`) runs the agents in order and returns one report each.
`build_orchestrator(settings)` gives the default line-up.

## The chat: a fleet on one question

`fleet.py` turns the agents into a conversation. `run_chat(request, db, settings)` yields events
that `POST /api/v1/chats` streams as server-sent events, and the Agents tab draws them as they land.

```
planning -> plan {agents, company} -> agent {id, running} -> agent {id, done, summary, findings,
sources, ms, cached} ... -> writing -> token ... -> done {ms}
```

| Step | What runs | Cost |
|---|---|---|
| Planner | one model call picks the agents the question needs; rules if the model fails | about 3 s |
| Data agents | `score`, `monitor`, `credit`: SQL over the serving tables, no model | milliseconds |
| Web agents | `sector` (any group), `context` and `peers` (real companies only), cached | 0 s cached, 10 to 60 s live |
| Writer | one streamed model call over the reports, in the language of the question | first token about 3 s |

Two constraints shaped it. Helmcode stalls concurrent requests on one key, so searches run in
parallel but model calls go through `SerialLLM`, one at a time. And `glm5.3` thinks for 25 s by
default, so the chat asks for `reasoning_effort="low"`: first token in 3 s. The batch agents keep
the default effort.

`GET /api/v1/agents` lists the roster for the side rail. Without `HELMCODE_API_KEY` the chat still
answers, with the data agents' summaries and no prose.

## Tools

One module per external service under `tools/`. `tavily.py` wraps the Tavily search
endpoint over `httpx`, keyed by `TAVILY_API_KEY`. `exa.py` does the same for Exa semantic
search, keyed by `EXA_API_KEY`. Plain search finds a company's rivals; `category="company"` was tried and returns look-alike home pages instead. `sources.py` ranks domains by trust and reads
publication dates; `cache.py` is the JSON cache with a TTL.

## Model

`llm.py` holds the `LLM` protocol and `OpenAICompatibleLLM`, a chat-completions client
over httpx. `build_llm(settings)` points it at Helmcode (`HELMCODE_API_KEY`,
`XRAY_LLM_MODEL`, default `glm5.3`) or returns None when there is no key.

## State of each agent

- Context retrieval works end to end and is cached. Pipeline, source tiers, dates, cache and what
  was tried and dropped: `docs/architecture.md` section 8. QA: `make context NAME="Cabify"`,
  add `REFRESH=1` to search again. Cached reports live in `data/serving/context/`.
- Macro returns a placeholder. Data source not chosen.
- Narrator ranks weak pillars deterministically. The prose pass is not wired.

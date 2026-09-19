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

## The chat: a planner directing a fleet

`fleet.py` turns the agents into a conversation. `run_chat(request, db, settings)` yields events
that `POST /api/v1/chats` streams as server-sent events, and the Agents tab draws them as they land.

Every agent is the same contract: **a purpose, rules, tools**. Rules are code and are shown on
screen. Each tool call is a `step` event, so what an agent is doing is visible while it does it.
No number comes from the model: it classifies the question and writes the answer, SQL over the
serving tables produces every figure.

```
planning -> plan {purpose, agents, company}
  -> agent {id, running} -> step {agent, n, tool, input, running} -> step {..., done, output, ms}
  -> agent {id, done, summary, findings, sources, ms}
  -> dispatch {agents}            the planner's one follow-up, decided by rules
  -> suggestion {agent, title, detail}
  -> writing -> token ... -> done {ms}
```

| Agent | Answers | Tools | Reads |
|---|---|---|---|
| Diagnosis | why the score moved, bump or fall | `pillars_at`, `drivers_window`, `own_history_rank` | `scores`, `drivers` |
| Monitor | when it was first visible | `alerts_for` | `alerts` |
| Working capital | the line, its price, what raises it | `offer_at`, `actions_ranked` | `offers`, `actions` |
| Customers | who pays late, concentration, who to chase | `concentration`, `payer_scores`, `overdue_ranked` | `payers` (groups with an ERP only) |
| Investor | search fund target, roll-up piece or neither; debt capacity | `cash_profile`, `debt_capacity`, `screen`, `comparables` | `scores`, `groups` |
| Market | is it us or the market | `exa.search`, `tavily.search`, `model.read` | the web, cached a week |

How a question runs:

1. **Planner** (one model call, about 3 s, rules if it fails) reads what the question is for
   (`diagnose`, `anticipate`, `collect`, `finance`, `invest`, `market`) and dispatches only the
   agents it needs. Diagnosis always runs. Agents run in parallel threads.
2. **Follow-up**, at most once and by rule, not by the model: if Diagnosis finds collections
   dragging the level, Customers is dispatched; if the state is bending or falling, Monitor is.
3. **Draft suggestion**, when the user asked what to do: the customer to chase, or the top ranked
   move. Built from figures. Anything that moves money is a draft a person signs.
4. **Writer** streams the answer from the reports, in the language of the question.

What the data does not allow is stated as a rule instead of guessed: counterparty ids do not link
to other groups, so a customer is judged only on how it paid this group; there is no sector and
no valuation multiple, so the Investor estimates no enterprise value. The Market agent reads the
country when there is no sector, and competitors only for a real company the user names.

Two constraints shaped the runtime. Helmcode stalls concurrent requests on one key, so searches
run in parallel but model calls go through `SerialLLM`, one at a time. And `glm5.3` thinks for
25 s by default, so the chat asks for `reasoning_effort="low"`: first token in 3 s.

`GET /api/v1/agents` lists the roster with purposes, rules and tools for the side rail and the
inspector. Without `HELMCODE_API_KEY` the chat still answers, from rules and raw reports.

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

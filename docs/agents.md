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

## The chat: a director over the whole portfolio

`fleet.py` turns the data and the agents into a conversation. It is not tied to a group: the
question can be about the portfolio, several groups, one group, or the raw trail under a score.
`run_chat(request, db, settings)` yields events that `POST /api/v1/chats` streams as server-sent
events, and the Agents tab draws them as they land. The request is a message, the month on
screen, the recent turns and the display currency.

The **director** is a loop, not a fixed plan. Each round the model sees the schema of every table
(read live from DuckDB), the roster with each agent's rules, what has come back so far and which
round it is on, and returns the next calls as JSON. Two kinds of call:

- `query`: one read-only SELECT over any table. The model writes the SQL, the database produces
  every figure. Rows come back as text, at most 40, so a question is answered by aggregating. A
  query that fails goes back to the director with its error, and it corrects it next round.
- an agent pointed at **any** `group_id` and `month`, with optional `tools` (narrow it),
  `compare` (peers), `what_if` (simulator) and `company` (market).

Every call is checked before it runs: group ids are respelled as the tables spell them
(`group_0130` becomes `GROUP_0130`), the month is clamped to the month on screen, a `what_if`
written as `{"pillar": ..., "points": ...}` is read. An agent pointed at a month the group has no
score for fails with the group's last scored month before it, and the director re-points the
call there. An answer that is not a valid move goes back to the model once with its error (a
transport error does not: the rules or the results stand in); `complete_json` reads the object
out of any prose or fence around it.

Calls of one round run in parallel threads. The loop ends when the director returns no calls,
marks a round `final` and every call in it ran, or after four rounds. Then the writer streams
the answer from the results, in the language of the question, and every figure in it is checked
against those results.

```
planning -> plan {purpose, agents: [{run, id, reason, target}]}
  -> step {run, n, tool, input, running} -> step {..., done, output, ms}
  -> agent {run, id, done, summary, findings, sources, ms}     or {failed, error}
planning -> plan ...                     the next round, when the director wants more
  -> suggestion {agent, title, detail}
  -> writing -> token ... -> check {figures, untraced} -> done {ms}
```

| Agent | Answers | Tools | Reads |
|---|---|---|---|
| Query | anything the tables hold, across groups and months | `sql` | every view in DuckDB |
| Scorecard | why this score, since when, what the monitor fired | `pillars_at`, `drivers_window`, `own_history_rank`, `alerts_for` | `scores`, `drivers`, `alerts` |
| Ledger | who pays late, who to chase, cash and debt capacity | `concentration`, `payer_scores`, `overdue_ranked`, `cash_profile`, `debt_capacity` | `payers` (groups with an ERP only), `scores` |
| Simulator | the line, its price, what a move does to it | `offer_at`, `actions_ranked`, `what_if` | `offers`, `actions`, `scores` |
| Peers | standing, a named comparison, the search fund screen | `standing`, `compare`, `screen`, `comparables` | `scores`, `drivers`, `groups` |
| Macro | the country around the group | `exa.search`, `model.read`, `cache.read` | the web, cached a week |
| Market | a real company the user names | `exa.search`, `tavily.search`, `model.read` | the web, cached a week |
| Notifier | who is told, and where, when the monitor fires or the score crosses a line | `rules.parse`, `rules.list`, `rules.add` | `data/serving/alert_rules.json` |

**What the query can read.** The serving tables always. Locally, `api/main.py` also registers
the cleaned raw trail from `data/processed/` (`transactions`, `invoices`, `balances`,
`debt_products`, `banking_products`, `debt_schedule_config`, and `raw_companies`, `raw_groups`
where a serving table has the name). The API image does not carry them (250 MB), so the deployed
chat answers from the serving tables only. The director is told which tables exist, not which
could.

**The SQL is written by a model, so it is boxed in.** `run_query` accepts exactly one statement
of type SELECT (`duckdb.extract_statements`), stops at 40 rows and interrupts after 20 s. At
startup the API sets `allowed_directories` to the data directories and turns
`enable_external_access` off, which DuckDB does not allow back on while running: no file outside
the data can be read and nothing can be written.

**Draft suggestion**, when the question asks what to do: the customer to chase, or the top ranked
move. Built from figures the agents found, never by the model. Anything that moves money is a
draft a person signs.

**Without a model** (`HELMCODE_API_KEY` unset, or the director failing on the first round) rules
stand in: a group id named in the question, in any case, gets Scorecard plus the agents its words
match (`PURPOSE_RULES`) at its last scored month on or before the month on screen, a second id is
compared, and a question that names no group reads the portfolio by state. The answer is then
the raw results.

The notifier keeps one copy of a rule: a request identical to one in force is reported as such
and nothing is added. A request that names no channel, or email and no address, saves nothing:
the report asks "Slack or email?" or "Which email address?", the writer ends its answer with
those words, and the next message that names a channel or an address goes straight to the
notifier (no director round) and is read together with the turns of the request before it. An
email rule carries its address; `notify` sends there. A bare group number (`the 0130`) is respelled as
`GROUP_0130` against the tables. Text that asks to be told nothing (a question about the rules,
a request to email this answer, pasted text) makes no rule.

What the data does not allow is stated as a rule instead of guessed: counterparty ids do not link
to other groups, so a customer is judged only on how it paid this group; there is no sector and
no valuation multiple, so no enterprise value is estimated.

Two constraints shaped the runtime. Helmcode stalls concurrent requests on one key, so searches
run in parallel but model calls go through `SerialLLM`, one at a time. And `glm5.3` thinks for
25 s by default, so the chat asks for `reasoning_effort="low"`: a round of the director is about
3 s, a typical answer 10 to 20 s.

`GET /api/v1/agents` lists the roster with purposes, rules and tools: the chat shows them when a
line of the trace is opened.

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

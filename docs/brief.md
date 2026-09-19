# X Ray: challenge brief and product decision

Single source of truth for what Embat asked and what we decided to build. Written from the
official challenge page (Spanish, `claude.ai/artifact/8N8Q7QMjprCUWxGAiJaWoP`), translated and
reorganised. Sections 1 to 6 are the organisers' words. Section 7 onwards is ours.

`HackSpain 2026` · Embat challenge · 18-20 September 2026 · ETSIT UPM, Madrid

---

## 1. The premise

> Can money tell you how a company is doing?

They hand us the financial trail of 250 business groups over 24 months. From it we build a
**financial health score**, and on top of the score, **a product that can be sold to those same
companies**. The score is the engine. What we mount on top is our choice.

Headline numbers as the organisers state them:

| | |
|---|---|
| Data | 250 companies, 24 months |
| Hidden test | 60-80 companies with no result |
| Deliverable | the score, and something sellable on top |

### The problem, in their words

Every company leaves a trail. Money comes in, invoices are issued, suppliers are paid, customers
pay, debt is drawn and repaid. That trail changes every day and almost nobody reads it. What
people look at are still photos: accounts that arrive late, ratings refreshed now and then.

The worked example, and the one to use in the pitch:

```
NORTHBROOK FOODS    45 -> 65
VELASCO INDUSTRIAL  82 -> 68
```

At month 24 the two are three points apart. One is a far better risk than the other, and today's
snapshot cannot tell which. That is what they want us to extract from the trail.

---

## 2. The six questions the system must answer

Per company and per month. "This is not about predicting bankruptcies. It is about reading
financial behaviour in both directions, and doing it before it is obvious."

1. **Who is healthy.** Not only who is in trouble. Recognising an exceptionally solid company is
   as useful as spotting the one that is sinking.
2. **Who is improving.** A company going 45 -> 65 may have mediocre numbers today and be next
   year's best bet.
3. **Who is starting to bend.** 82 -> 68 still looks healthy. But something in its behaviour has
   already changed and it is worth seeing now.
4. **Bump or fall.** A bad cash month is not the same as structural deterioration. The system has
   to separate them.
5. **Why it changed.** A number without an explanation is useless for deciding. You need to know
   which signal moved, and when.
6. **When it was visible.** Detecting something the month it happens is worth little. The value is
   in how many months earlier the system saw it.

---

## 3. Four things the system must do

The first three build the engine. The fourth turns the engine into something somebody signs.

| | |
|---|---|
| **Read the trail** | Bank movements, invoices issued and received, payment behaviour, cost of financing, debt balances. 24 months per company. The signals come from here; the work is deciding which ones matter. |
| **The score, the axis** | A score that captures trajectory, not just the last month's photo, and that holds up on the 60-80 companies the system never sees. Everything else rests on this. If the number is no good, neither is the product. |
| **Explain itself** | Why this company gets this number, and why it changed since last month. "Nobody buys a black box to decide who to lend to or who to insure." |
| **Build something on top** | A product, service or tool resting on the score that somebody would pay to use. And knowing who you sell it to. Hint from the organisers: the company that hands you the data is the most obvious buyer. |

---

## 4. The dataset

1,286 synthetic companies grouped into **250 business groups**, 24 months of history each
(September 2024 to September 2026), in **nine CSV files** (also available as JSON).

Generated from the statistical distribution of real SME treasury data: volumes, seasonality,
counterparty patterns and financing conditions behave like the real thing. No row corresponds to a
real company, account or person.

| File | Contents |
|---|---|
| `groups.csv` | One business group per row. A group can be a holding with several subsidiaries: 1 to 24 companies, median 2. |
| `companies.csv` | One company per row: group, country, currency, ERP, signup date. `company_id` is the key that joins every other file. |
| `banking_products.csv` | Bank accounts: current, card, POS, savings, investment, expense platform, with bank and currency. |
| `debt_products.csv` | Financing: loans, leasing, credit lines, mortgages, renting, factoring, confirming, guarantees. Granted amount and outstanding balance. |
| `debt_schedule_config.csv` | Terms of loans with an amortization schedule: installment type, frequency, number of installments, interest rate, next payment date. |
| `transactions.csv` | Bank movements over the 24 months: date, amount, category, reconciliation status, counterparty, bank concept. |
| `invoices.csv` | Invoices synced from the ERP, issued and received: issue, due, collection or payment date, pending amount, status, counterparty. |
| `balances.csv` | Balance of each account and product at 1 September 2026, the final photo. |
| `data_dictionary.md` | Every field explained, file by file. Read it before engineering features. |

---

## 5. What the submission must contain

| What | What it means | Status |
|---|---|---|
| Prediction on the hidden test | The system scores companies it has never seen. This is what enters the leaderboard. | **Mandatory** |
| Signal in both directions | Recognises improvement as well as deterioration. A plain bankruptcy detector falls short. | **Mandatory** |
| Trajectory, not a photo | The output reflects where the company is heading, not only where it stands in the last month. | **Mandatory** |
| Explanation | For any company, we can say why it gets that number and what moved it. | **Mandatory** |
| Product on top of the score | Something built on the number: a marketplace, a policy, a working-capital line, an agent. The score alone is not the deliverable. | **Mandatory** |
| Identified buyer | We can say who pays for it and why it pays off for them. Not a business plan, an answer. | **Mandatory** |
| Navigable demo | Something that opens and can be tried in front of the jury. A notebook that only runs on our laptop does not count. | **Mandatory** |
| Measured anticipation | We show how many months earlier it detects the change, not just that it detects it. | Bonus |
| Monitor that alerts | The system does not wait to be asked: it raises its hand when a company really moves. | Bonus |

---

## 6. How we are judged

Three blocks. **None weighs more than the others.** "A simple model with a clear product on top
interests us more than a sophisticated one that stops at the number."

**Is it right**
- *Generalization*: does it work on companies it has never seen?
- *Trajectory*: does it capture the direction of movement or only today's level?
- *Both faces*: does it detect improvement as well as deterioration?

**Is it on time**
- *Anticipation*: does it see the change before it is obvious in the numbers? How many months
  earlier, measured.
- *Stability*: does it tell a one-off bump from real deterioration?
- *Monitor*: extra points if it also alerts on its own, unprompted.

**Is it worth something**
- *Product*: is there something built on top of the score, or does it stop at the number?
- *Buyer*: do we know who pays and why it pays off? The company that generates the data is the
  obvious candidate.
- *Explanation*: can we tell why a company gets that number?
- *Craft*: is it well built, and does the care show? And the demo opens and can be tried.

### Ideas the organisers listed (open, not a closed list)

Credit marketplace · financial insurance with a premium that moves with the score · working-capital
financing with a limit that recalculates itself monthly · a recommendations agent that reads the
trail and says what to do this week · sector-level prediction sold to investors · anything else
(dynamic pricing, supplier scoring, a seal companies show to negotiate, a conditions comparator).
"If somebody is willing to pay for it, it counts."

### What the organisers provide

- The dataset in CSV and JSON with a one-page data dictionary.
- **The hidden test, the scoring script and the leaderboard, from Friday.** We can measure
  ourselves all weekend instead of finding out on Sunday.
- Two engineers rotating in the room all weekend, plus a data specialist reachable at night.
- **Saturday morning, 30 minutes** on how money really moves inside a company: where each file
  comes from and what it means. Someone from the team must attend.
- Their closing warning: the demo counts as much as the product. However good the signal, if in
  five minutes it is not clear who it is sold to and why, it falls short. Keep time to rehearse
  the pitch.

---

## 7. What we are building

**Product: X Ray.** A financial health radar for the CFO, sitting on top of the treasury data
their bank aggregator already holds.

**Buyer: Embat.** They pay, their CFO customer uses it. Embat already holds the data, so customer
acquisition cost is zero, and the upside is ARPU expansion on existing accounts plus an
origination fee when a working-capital offer is taken up through a partner lender.

**Pitch in one line:** *"What will my bank think of me in three months, and what do I do about it
this week?"*

Six layers, each one mapped to a scoring block so nothing is built that the rubric does not pay
for:

| Layer | What the CFO sees | Rubric it covers |
|---|---|---|
| **Score** | One number per group per month, level and trend, over the full 24 months | Generalization, trajectory, both directions |
| **Explanation** | Which named drivers moved, when, and which subsidiary pressures the group score | Explanation |
| **Monitor** | An alert when the score *really* moves, silence on a one-month dip | Monitor, stability |
| **Offer** | A working-capital limit and price recalculated monthly from the score: up when improving, tightening early when bending | Product, buyer, both directions |
| **Actions** | Three ranked moves, each tied to a driver, each with its expected score impact | Product, buyer |
| **Backtest** | "Detected N months before it showed in the level", replayed over the 24 months | Anticipation, measured |

### The demo, five minutes

It runs live. `make lighthouse` brings the whole thing up in one terminal (data, API, web).
`make demo CHANNEL=slack` in a second one connects 24 named scale-ups to the portfolio in two
arrivals, scored the second they land, with a Slack message naming each newcomer's state; or
`make replay FROM=2025-01 PAUSE=8 CHANNEL=slack`, started before walking on:
every eight seconds a month of data lands, the score is recomputed from what was known by then,
the web refreshes on its own and the month's alerts arrive in the Slack channel on the projector.
Nobody clicks anything to make the portfolio move. With `CHANNEL=rules` only what was asked for
in the chat leaves ("Slack me when a group starts falling, email me everything on Velasco",
"an alarm when the 0130 gets a score above 80"): each alert is `info`, `warning` or `critical`; a
rule names a channel, the groups it watches and what it waits for: alerts from an urgency up
with an optional severity floor, or the score crossing a line. An email rule carries its
address. A request that names no channel, or email and no address, saves nothing; the chat asks
for what is missing and the answer completes it.

1. Open Northbrook (45 -> 65), then Velasco (82 -> 68) at month 24. Similar levels, opposite bets.
2. Read their trajectories in turn: Northbrook rises while Velasco bends.
3. Open Velasco's drivers: what moved, and in which month.
4. Show the monitor entry that fired at month 14, and the backtest saying it was visible N months
   before the level moved.
5. Show the two offers the engine produces: Northbrook's limit going up, Velasco's tightening.
   Name the buyer and the money.

### Scope: what we are not building

No user accounts, no multi-tenant, no real lender integration, no live data ingestion, no mobile.
The demo is read-only over precomputed results.
The main group view has a floating AI chat backed by the Helmcode fleet, scoped to the selected group, month and display currency.
The optional local scorecard provides company/group views and uses the AI button for temporary pillar weights and chart settings.
The view assistant reads evidence through the selected month and changes browser settings without writing data or recomputing component scores.

---

## 8. Mapping deliverables to the repo

Pipeline shape, the panel contract and the reasoning behind both: `docs/architecture.md`.

| Deliverable | Where it lives |
|---|---|
| Load and validate the nine CSVs | `src/xray/pipeline/data.py`, `src/xray/config.py` |
| Clean the raw tables to parquet | `src/xray/pipeline/clean.py` |
| Convert money columns to euros with annual rates | `src/xray/pipeline/fx.py`, `src/xray/pipeline/fx_rates.csv` |
| Monthly panel per group, no look-ahead | `src/xray/pipeline/panel.py` |
| Daily extracts, as-of reads | `src/xray/pipeline/lake.py` |
| Whole pipeline end to end | `python -m xray.pipeline`, `make panel`; everything up to a running API and web: `make lighthouse` |
| Anchor table: raw ratio to 0-100, pillar weights | `src/xray/scoring/anchors.py` |
| Level score, per group or per company | `src/xray/scoring/score.py` |
| Provisional score and drivers for the local internal viewer | `src/xray/scoring/score_baseline.py`, `make score-baseline` |
| Optional local company/group scorecard and export | `src/xray/v2.py`, `src/xray/v2_scores.py`, `src/xray/scoring/local_serving.py`, `api/routers/scoring.py`; setup in `docs/local-scoring-v3.md` |
| Proxy distress labels for validation | `src/xray/scoring/events.py` |
| Discrimination, trajectory, stability, ablation | `src/xray/scoring/validate.py` |
| Smoothing, slope, state machine on the level series | `src/xray/scoring/trend.py` |
| Named driver decomposition | `src/xray/scoring/explain.py` |
| Company pressure on the group score | `src/xray/scoring/company_impact.py` |
| Bump vs fall, alerting | `src/xray/scoring/monitor.py` |
| Alert delivery to Slack or email | `src/xray/scoring/notify.py`, `src/xray/integrations/` |
| Who is told, where, from which urgency or score line: the rule book, written in plain words through the chat | `src/xray/scoring/rules.py` (`data/serving/alert_rules.json`), `src/xray/agents/notifier.py` (the `notifier` fleet member), `api/routers/alert_rules.py`, `make replay CHANNEL=rules` |
| Limit, price, ranked actions | `src/xray/scoring/offer.py` |
| Context around the score: public research, macro, narrative of weak pillars | `src/xray/agents/`, see `docs/agents.md` |
| Natural-language view controls and local evidence | `src/xray/agents/view.py`, `api/routers/view_chat.py`, `web/src/components/ViewAgent.tsx`, `web/src/lib/viewAgent.ts` |
| Floating AI chat in the main group view | `web/src/components/ViewAgent.tsx`, `web/src/lib/viewAgent.ts`, `api/routers/chat.py`, `src/xray/agents/fleet.py` |
| Hidden-test predictions for the leaderboard | `src/xray/scoring/submit.py`, `make submit RAW=dir` |
| Live demo: months land one at a time, the web and Slack follow | `src/xray/pipeline/replay.py` (`make replay`), `serve.publish`, `api/routers/version.py`, `api/routers/tables.py`, polling in `web/src/App.tsx` |
| Live demo: named companies connect to the platform in batches and are scored on the spot | `src/xray/pipeline/synth.py` (the synthetic dump), `src/xray/pipeline/onboard.py` (`make demo`) |
| Precomputed results the demo reads | parquet in `data/serving/`, written by `src/xray/scoring/serve.py` (`make serve`), read by the API through in-memory DuckDB |
| API for the demo | `src/xray/api/`, one router per resource in `routers/` (see `.claude/rules/api-design.md`) |
| Runtime settings from `.env`, `XRAY_` prefix | `src/xray/settings.py`, `.env.example` |
| API container, CI | `Dockerfile` (target `api`), `docker-compose.yml`, `.github/workflows/ci.yml` |
| Demo front end | `web/` (Vite + React), `make web`, deployed as a static site via `render.yaml` |
| Reproducible build on any laptop | `Dockerfile`, `make docker-build`, `make docker-pipeline` |

The model team codes against `data/marts/panel_group.parquet`: 250 groups x 24 months, every
column computed from data at or before that month. Check `has_erp` before touching the invoice
columns, and `is_covered` before reading a level. Operating flows are `inflow_op`/`outflow_op`
and their `opin_3m`, `opout_3m`, `opin_12m`, `opout_12m` windows: use those, not `inflow` and
`outflow`, which include intragroup transfers and net to the wrong sign at portfolio level.

Score design and data constraints: `docs/health-score-research.md`. Infrastructure flow: `docs/infra.md`.

---

## 9. Modelling guardrails (non-negotiable)

- **The unit of scoring is the group.** Aggregate companies up to it. Split train/validation **by
  group**, never by row or by month, to mimic the hidden test.
- **The optional local scorecard also exposes companies.** Its configuration and serving export are separate from the baseline engine.
- **AI weight actions blend existing local pillars.** The session overlay does not alter component scores, stored observations or the baseline engine.
- **AI charts require two finite observations per series in the visible period.** Missing observations remain missing; a snapshot is not a historical series.
- **The view prompt requires evidence for facts, numbers and dates.** It requires missing data to be acknowledged and relationships to be identified as interpretations, without invented causal explanations.
- **No look-ahead.** A feature for month `t` uses only data up to `t`. `balances.csv` is a final
  snapshot at 1 Sep 2026, so it is month-24 information only and cannot feed any earlier month.
- **Debt fields are extraction-time too.** `debt_products.outstanding`, `granted` and `liquidity`
  describe 1 Sep 2026. For month `t` use the dated debt flows in transactions.
- **Money columns are converted to euros at the average rate of their year.** Cash is
  reconstructed in each account's currency before month-by-month conversion.
- **Monthly balances are reconstructed backwards**: final balance minus the flows after `t`, per
  account.
- **Invoices cover 167 of 250 groups.** Invoice pillars are optional and weights renormalise; the
  score works on transactions alone.
- **Every score decomposes into named drivers.** No black box: the explanation layer is a graded
  deliverable, not a nice-to-have.
- **Separate level from trend**, and a one-month dip from a sustained move. The monitor depends on
  this distinction and so does a whole scoring sub-block. A six-month smoothed slope of at least
  1.5 points per month in either direction raises that alarm and clears the opposite CUSUM.
- **`status` and `pending_amount` on invoices are as-of-extraction, not as-of-month-`t`.** An
  invoice reading `paid` today was `pending` in month 10. Derive state from dates instead. The
  panel already does; anything reading the raw invoices must too.
- **Operating flow excludes `transfer`, the two `investment_*` categories, `cash_settlement`,
  `cash_withdrawal` and debt service.** All-in flows show the portfolio 8.5bn in surplus;
  operating flows show it 11bn in deficit. Intragroup transfers were masking the deficit.
- **The score is calibrated and validated against proxy events, never trained on them.** With
  ~244 labelable groups and ~50 positives, a fitted model would memorise the training groups.
- **`cash_negative` is the event the data supports.** The level reaches 0.910 AUC against it on
  held-out groups (bottom level quintile 51.6% forward negative cash, top 0.6%). `missed_payroll`
  (0.593) and `inflow_collapse` (0.392) are not predictable from the financial trail and are
  reported beside the score, not folded into it.
- **Weights follow measured discrimination, not the opening guess.** Liquidity 0.40, payment
  discipline 0.20, cash generation 0.20, collections 0.10, debt burden 0.10. Only liquidity and
  debt burden improve the negative-cash AUC; the other three cost it under 0.02 each and are kept
  for the explanation and for whatever the hidden metric turns out to reward.
- **Every flow indicator is a ratio of trailing sums**, never one month's ratio: margin over 6
  months, lateness over 3, growth as the 3-month run rate against the trailing 12. Monthly flows
  swing several-fold for an ordinary group. This alone took the level from 4.07 to 2.45 median
  points of month-on-month change; every indicator is available from a group's first month, so no
  pillar joins late and moves the level for a reason that is not the group's.
- **Overdue invoices count only while under 90 days past due.** The open-book overdue ratio
  drifts towards 1 for every group because unpaid rows never close; the 90-day version is flat
  over the window and rank-orders forward negative cash equally well (AUC 0.652 vs 0.647).
- **A zero balance is not an overdraft.** Reconstructed cash lands at plus or minus 1e-10 on an
  emptied account depending on summation order; overdrawn means below minus one unit.
- **The trend does not predict liquidity events beyond the level.** On the raw level, a falling
  6-month slope is followed by mean reversion (corr with the next 6 months' change -0.2); on the
  smoothed level it is weakly persistent. Direction is a description of where the group is going,
  not a second predictor, and `compound` is priced as such.
- **Anticipation is measured on the level series, not on proxy events.** Of the 11 groups that
  went negative after six clean months, 73% had a smoothed level 5 points below its running
  peak at least 7 months earlier (median), and the CUSUM alarm led the event by 6 months.
- **A group scores the same alone as inside the portfolio.** Nothing is fitted, so 70 groups
  cut out of the raw CSVs and scored on their own reproduce the full run to the last decimal;
  `tests/scoring/test_submit.py` keeps that true.

---

## 10. Open questions, resolve on Friday

Things the brief leaves genuinely ambiguous. Ask the Embat engineers in the room rather than
guessing.

1. **Is the hidden test 60-80 groups or 60-80 companies?** The headline says "60-80 empresas", the
   dataset is 250 groups / 1,286 companies, and our guardrail scores groups. The submission format
   in the scoring script settles it. Until then assume groups.
2. **What is the target and the leaderboard metric?** The brief never names either. The scoring
   script lands Friday. Everything about model choice waits for this.
3. **What is the ground-truth result?** No file in the dataset carries a label, so the score is a
   fixed-rule scorecard validated on proxy events. "empresas sin resultado" implies the scoring
   script holds a result per company. Find out what it is.
4. **Who exactly is the buyer, in their reading?** The brief says both "the company that hands you
   the data" (Embat) and "the company that generates the data, which is the first one interested in
   knowing what it says about it" (the SME). Our answer covers both: Embat pays, the SME uses. Say
   it that way in the pitch.
5. **What does `accounting_status = DISCARDED` mean?** 308k transactions. If they are rejected
   movements they leave operating flow.
6. **Per-month scores or only the final month?** Trajectory is mandatory, so we produce all 24
   either way, but the submission may only take one.
7. **Is invoice direction really the sign of `amount`?** There is no direction column. We read
   positive as receivable and negative as payable, which gives a plausible 13-day median DSO and
   21-day DPO, but confirm it before the score depends on it.
8. **Group names for the demo.** The dataset has none, so `groups.name` is the `group_id`. The
   brief's worked example maps onto real groups: `GROUP_0220` is Velasco (94 in Jan 2025,
   bending alarm in Jun 2025 at 82 while still healthy, tier crossed to coping in Oct 2025, 64 at
   month 24), `GROUP_0043` is Northbrook (41 to 81, improving). Decide whether to show ids or
   invent trading names.
9. **The serving `alerts` table is the monitor's schema**, wider than the contract in
    `docs/serving-contract.md` (kind, direction, sigmas, resolution, severity). Align the
    contract or the front end.

---

## 11. Working agreements for agents

Read `CLAUDE.md` and `.claude/rules/` before writing code. `AGENTS.md` explains how the rules are
scoped for non-Claude agents.

- Several people and agents work in this same checkout. Stage only the files you changed, never
  `git add -A`. Do not switch branches or rewrite history without asking.
- `data/` is git-ignored and stays that way. The dataset is synthetic but it does not go into git.
- Before saying done: run the code, then `make ci`.
- Keep time for the pitch. The demo counts as much as the product.

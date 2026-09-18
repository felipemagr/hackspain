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

Five layers, each one mapped to a scoring block so nothing is built that the rubric does not pay
for:

| Layer | What the CFO sees | Rubric it covers |
|---|---|---|
| **Score** | One number per group per month, level and trend, over the full 24 months | Generalization, trajectory, both directions |
| **Explanation** | Which named drivers moved, when, and which subsidiary drags the group | Explanation |
| **Monitor** | An alert when the score *really* moves, silence on a one-month dip | Monitor, stability |
| **Offer** | A working-capital limit and price recalculated monthly from the score: up when improving, tightening early when bending | Product, buyer, both directions |
| **Actions** | Three ranked moves, each tied to a driver, each with its expected score impact | Product, buyer |
| **Backtest** | "Detected N months before it showed in the level", replayed over the 24 months | Anticipation, measured |

### The demo, five minutes

1. Open on Northbrook (45 -> 65) and Velasco (82 -> 68) side by side at month 24. Three points
   apart, opposite bets.
2. Pull the trajectory. The two curves cross.
3. Open Velasco's drivers: what moved, and in which month.
4. Show the monitor entry that fired at month 14, and the backtest saying it was visible N months
   before the level moved.
5. Show the two offers the engine produces: Northbrook's limit going up, Velasco's tightening.
   Name the buyer and the money.

### Scope: what we are not building

No user accounts, no multi-tenant, no real lender integration, no live data ingestion, no mobile.
The demo is read-only over precomputed results. Anything that does not appear in the five minutes
above does not get built.

---

## 8. Mapping deliverables to the repo

Pipeline shape, the panel contract and the reasoning behind both: `docs/architecture.md`.

| Deliverable | Where it lives |
|---|---|
| Load and validate the nine CSVs | `src/xray/data.py`, `src/xray/config.py` |
| Clean the raw tables to parquet | `src/xray/clean.py` |
| Monthly panel per group, no look-ahead | `src/xray/panel.py` |
| Daily extracts, as-of reads | `src/xray/lake.py` |
| Whole pipeline end to end | `src/xray/pipeline.py`, `make panel` |
| Score, level and trend | `src/xray/score.py` |
| Named driver decomposition | `src/xray/explain.py` |
| Bump vs fall, alerting | `src/xray/monitor.py` |
| Alert delivery to Slack | `src/xray/notify.py` |
| Limit, price, ranked actions | `src/xray/offer.py` |
| Hidden-test predictions for the leaderboard | `src/xray/submit.py` |
| Precomputed results the demo reads | parquet in `data/serving/`, written by the pipeline, read by the API through in-memory DuckDB |
| API for the demo | `src/xray/api/` (see `.claude/rules/api-design.md`) |
| Runtime settings from `.env`, `XRAY_` prefix | `src/xray/settings.py`, `.env.example` |
| API container, CI | `Dockerfile` (target `api`), `docker-compose.yml`, `.github/workflows/ci.yml` |
| Demo front end | to be decided, deployed, not localhost-only |
| Reproducible build on any laptop | `Dockerfile`, `make docker-build`, `make docker-pipeline` |

The model team codes against `data/processed/panel_group.parquet`: 250 groups x 24 months, every
column computed from data at or before that month. Check `has_erp` before touching the invoice
columns, and `is_covered` before reading a level.

Score design and data constraints: `docs/health-score-research.md`. Infrastructure flow: `docs/infra.md`.

---

## 9. Modelling guardrails (non-negotiable)

- **The unit of scoring is the group.** Aggregate companies up to it. Split train/validation **by
  group**, never by row or by month, to mimic the hidden test.
- **No look-ahead.** A feature for month `t` uses only data up to `t`. `balances.csv` is a final
  snapshot at 1 Sep 2026, so it is month-24 information only and cannot feed any earlier month.
- **Debt fields are extraction-time too.** `debt_products.outstanding`, `granted` and `liquidity`
  describe 1 Sep 2026. For month `t` use the dated debt flows in transactions.
- **Monthly balances are reconstructed backwards**: final balance minus the flows after `t`, per
  account.
- **Invoices cover 167 of 250 groups.** Invoice pillars are optional and weights renormalise; the
  score works on transactions alone.
- **Every score decomposes into named drivers.** No black box: the explanation layer is a graded
  deliverable, not a nice-to-have.
- **Separate level from trend**, and a one-month dip from a sustained move. The monitor depends on
  this distinction and so does a whole scoring sub-block.
- **`status` and `pending_amount` on invoices are as-of-extraction, not as-of-month-`t`.** An
  invoice reading `paid` today was `pending` in month 10. Derive state from dates instead. The
  panel already does; anything reading the raw invoices must too.

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
5. **Which way does `exchange_rate` convert?** Multiply or divide to reach the company currency.
   Needed before summing a multi-currency group.
6. **What does `accounting_status = DISCARDED` mean?** 308k transactions. If they are rejected
   movements they leave operating flow.
7. **Per-month scores or only the final month?** Trajectory is mandatory, so we produce all 24
   either way, but the submission may only take one.
8. **Is invoice direction really the sign of `amount`?** There is no direction column. We read
   positive as receivable and negative as payable, which gives a plausible 13-day median DSO and
   21-day DPO, but confirm it before the score depends on it.
9. **Does the open-invoice book need a censoring correction?** An invoice never paid inside the
   window stays open forever, so `ar_overdue_ratio` drifts from 0.21 to 0.78 across the 24 months
   for everyone. Part real, part an artifact of a 24-month window. Compare each group against the
   cross-sectional median for that month rather than against its own past level.

---

## 11. Working agreements for agents

Read `CLAUDE.md` and `.claude/rules/` before writing code. `AGENTS.md` explains how the rules are
scoped for non-Claude agents.

- Several people and agents work in this same checkout. Stage only the files you changed, never
  `git add -A`. Do not switch branches or rewrite history without asking.
- `data/` is git-ignored and stays that way. The dataset is synthetic but it does not go into git.
- Before saying done: run the code, then `make ci`.
- Keep time for the pitch. The demo counts as much as the product.

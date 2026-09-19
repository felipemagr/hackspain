# HackSpain 2026: X Ray (Embat challenge)

Full brief, product decision, demo script and open questions: [`docs/brief.md`](docs/brief.md). Read it first.
System shape, pipeline, the panel contract, the data traps it works around, agents and API: [`docs/architecture.md`](docs/architecture.md).
How the score is computed, every formula and constant as built, and how to change it safely: [`docs/scoring.md`](docs/scoring.md).

Hackathon project, 18-20 September 2026. Build a **financial health score** from the financial trail of companies, and a **sellable product on top of it**. The score is the engine; the score alone is not the deliverable.

## The challenge

- Data: 1,286 synthetic companies in 250 business groups, 24 months each (Sep 2024 to Sep 2026), nine CSV files. Fully synthetic.
- Hidden test: 60-80 groups the system never sees. Predictions on it feed the leaderboard.
- Judging, three equal blocks: **is it right** (generalization, trajectory, both directions), **is it on time** (anticipation in months, bump vs structural decline, self-alerting monitor), **is it worth something** (product, buyer, explanation, craft, demo that opens and works).
- A simple model with a clear product beats a sophisticated model that stops at the number.

## Six questions the system must answer, per company and per month

1. Who is healthy (not only who is in trouble).
2. Who is improving (45 -> 65 can be the best bet).
3. Who is starting to bend (82 -> 68 still looks healthy).
4. Bump or fall: one bad cash month vs structural deterioration.
5. Why it changed: which signal moved and when.
6. When it was visible: how many months ahead the system saw it.

## Deliverables

Mandatory:
- Predictions on the hidden test.
- Signal in both directions (improvement as well as deterioration).
- Trajectory, not a snapshot of the last month.
- Explanation: why this score, and what moved it since last month.
- A product on top of the score (marketplace, policy, working-capital line, agent...).
- An identified buyer. The company that generates the data is the obvious one.
- A navigable demo that opens in front of the jury. A notebook that only runs on one laptop does not count.

Bonus:
- Measured anticipation (how many months earlier).
- A monitor that raises its hand on its own when a company really moves.

## Dataset

| File | Contents |
|------|----------|
| `groups.csv` | One business group per row. 1 to 24 companies per group, median 2. |
| `companies.csv` | One company per row: group, country, currency, ERP, signup date. `company_id` joins everything. |
| `banking_products.csv` | Bank accounts: current, card, POS, savings, investment, expense platform. |
| `debt_products.csv` | Financing: loans, leasing, credit lines, mortgages, renting, factoring, confirming, guarantees. Granted amount and outstanding balance. |
| `debt_schedule_config.csv` | Amortization terms: installment type, frequency, number of installments, interest rate, next payment date. |
| `transactions.csv` | 24 months of bank movements: date, amount, category, reconciliation status, counterparty, bank concept. |
| `invoices.csv` | ERP invoices, issued and received: issue, due, paid date, pending amount, status, counterparty. |
| `balances.csv` | Balance of each account and product at 1 Sep 2026 (final snapshot). |
| `data_dictionary.md` | Every field explained. Read it before engineering features. |

## Modelling guardrails

- The unit of scoring is the **group**; aggregate companies up to it. Split train/validation **by group**, never by row or by month, to mimic the hidden test.
- No leakage from the future: a feature for month `t` uses only data up to `t`. `balances.csv` is a final snapshot, so treat it as month-24 information only.
- Every score must be decomposable into named drivers so it can be explained.
- Distinguish level from trend, and a one-month dip from a sustained move.
- Before working on features, scoring, explanation or the monitor, read `docs/scoring.md` (what is built: indicators, anchors, weights, state machine, invariants, recipes for changing each) and `docs/health-score-research.md` (why: data constraints, sources, the design space).
- The score is never fitted and never reads a population statistic. A group must score the same alone as inside the portfolio; `tests/scoring/test_submit.py` holds that.

## Working rules

See `.claude/rules/`:
- `coding-guidelines.md`: think first, keep it simple, surgical changes, lean comments.
- `python-style.md`: Python conventions.
- `testing-patterns.md`: lean, targeted tests.
- `api-design.md`: FastAPI conventions for the demo backend.
- `git-commits.md`: conventional commits.
- `frontend-design.md`: UI work goes through the `impeccable` skill; which skill owns what and in which order.

Keep time for the pitch: the demo counts as much as the product.

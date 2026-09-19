# Health score: research and design basis

The *why* behind the score: what the challenge asks, what the data allows, how practitioners score SME health from a money trail, and the design space we derived from that. Written 2026-09-18. Facts marked (unverified) came from memory, not from a source opened during the research.

The *what*, as built, is `scoring.md`: exact indicators, anchors, weights, state machine, validation numbers and recipes for changing them. Where this file and `scoring.md` disagree, `scoring.md` describes the code. The main departures from the design below, all measured against forward negative cash on held-out groups: weights moved to liquidity 0.40 / payment 0.20 / cash generation 0.20 / collections 0.10 / debt 0.10; the open-book overdue ratio was replaced by overdue under 90 days over paid flow; margin runs on 6 months and growth as the 3-month run rate over the trailing 12; no trend indicator lives inside the level, and the trend is measured on the level series and shown as direction, not used as a second predictor.

## 1. What the data forces on us

Measured on `data/processed/` (see `src/xray/clean.py`):

| Finding | Consequence |
|---|---|
| **No label exists** in any file: no default, no rating, no target score. | The score is an expert scorecard with fixed rules, not a trained classifier. Validation uses proxy outcomes built from the data itself (section 7). The hidden-test prediction format is still unknown: ask the organisers. |
| Invoices cover **167 of 250 groups** (785 of 1,286 companies). | Invoice pillars are optional. Weights renormalise over the pillars a group has. The score must still work on transactions alone. |
| `counterparty_id` is null on **90% of transactions**. | Customer concentration from transactions is unreliable. Use invoice counterparties where present, otherwise skip. |
| `balances.csv` is a single snapshot at 2026-09-01. | Monthly balances are **reconstructed backwards**: `balance(end of t) = final balance - sum of flows after t`, per account. Checked on 4,088 checking accounts: 91.5% of account-months come out non-negative, so it holds. This unlocks buffer days per month. |
| `invoices.status` and `pending_amount` describe extraction time, not month `t`. | Never use them for `t < 24`. Rebuild the state from dates: open at `t` if `issuance_date <= t` and (`payment_date` null or `> t`); overdue at `t` if also `due_date < t`. |
| `debt_products.outstanding`, `granted`, `liquidity` are snapshots too. | Credit-line utilisation and debt stock are month-24 only. For history use the flows: `debt_repayment`, `interest_charge`, `fee`. |
| Groups have a median of **18 active months** (min 1, 25% have 9 or fewer). | Every feature needs a minimum-history rule and a "not enough data" state. Trend needs at least 6 months. |
| `transfer` nets to +21bn across the dataset, so intragroup moves do not cancel. | Exclude `transfer`, `investment_deployment`, `investment_return` and `cash_settlement`/`cash_withdrawal` pairs from operating flow. |
| 4% of transactions carry `exchange_rate != 1`; 25% uncategorised. | Convert to one currency before summing a group (check the direction of the rate first). Operating inflow/outflow must not depend on the category being present: use sign for totals, categories for the named sub-signals. |
| Paid invoices: median 0 days late on both sides; p90 is 29 days (payables) and 40 days (receivables). | Lateness is a tail signal. Score the amount-weighted tail, not the median. |

On the reconstructed balance: it uses later flows arithmetically, but the value it yields is the balance that was observable at `t`. A live system would simply read it from the bank. It is not leakage.

## 2. What practitioners use

**Cash-flow underwriting** (FinRegLab small-business report, Mastercard Open Finance SB analytics, merchant cash advance underwriting): monthly inflows and their trend over 3 to 4 month aggregates, inflow volatility, average balance relative to monthly revenue, days with negative balance, returned payments, debt obligations against inflows, largest single inflow. Consensus: negative-balance days and returned payments move first; thinning balances plus falling revenue over 3 to 4 months is the structural pattern.

**Cash buffer days** (JPMorgan Chase Institute, 597k small businesses): balance divided by average daily outflow. Median **27 days**, bottom quartile **13 or fewer**, top quartile **62 or more**. These are our liquidity anchors.

**Payment behaviour in Spain** (Informa D&B): average delay **13.97 days** in Q4 2025, European average 12.28. Ley 15/2010 caps B2B terms at 60 days (unverified). Around 5% of payments run more than 60 days late.

**D&B Paydex**: amount-weighted days beyond terms mapped to 0-100. We reuse the table directly, with linear interpolation between points:

| Days beyond terms | early | on terms | 15 | 22 | 30 | 60 | 90 | 120 |
|---|---|---|---|---|---|---|---|---|
| Score | 100 | 80 | 70 | 60 | 50 | 40 | 30 | 20 |

**Debt service**: DSCR of 1.25 is the usual covenant floor, 1.0 is break-even (unverified).

**EBA/GL/2020/06, para 274**, early warning indicators a bank must monitor. Those our data can see: rising debt or debt-service ratio; significant drop in turnover or recurring cash flow, including loss of a major client; narrowing margins; outstanding debt not falling; significant change in payment behaviour; difficulties elsewhere in the group of related borrowers. The last one backs group-level scoring with a weakest-subsidiary flag. The EBA gives no numeric thresholds. Common bank triggers (unverified): line utilisation persistently above 80 to 90%, late tax or social security payments, payroll paid late, new lenders appearing.

**Composite score precedents**:
- *FinHealth Score*: 8 indicators, each mapped to 0-100 by fixed bands, pillar = mean of its indicators, total = mean of pillars. Tiers 0-39 vulnerable, 40-79 coping, 80-100 healthy. Closest template to ours.
- *Points scorecard (WoE, PDO)*: needs labels, which we lack. We keep its form: per-feature bands with additive points, so every contribution is readable.
- *Altman Z''*: needs a balance sheet, not computable. Precedent for fixed published weights.
- *CAMELS*: a failing pillar caps the composite. We adopt that as a cap rule.

Sources are listed in section 9.

## 3. Score architecture

```
raw tables -> monthly group features (as of t) -> indicator sub-scores 0-100
           -> pillar scores 0-100 -> level score 0-100 (+ cap rule)
           -> trend, state and alerts on the level series
```

Rules that keep it deterministic and explainable:

1. **Everything is a ratio**, so group size drops out. Denominator is usually trailing operating inflow or outflow.
2. **Trailing 3-month windows** for every flow feature. One bad month moves a 3-month ratio by a third, which already damps bumps.
3. **Fixed anchors, not population percentiles.** Each indicator maps to 0-100 through a piecewise-linear function with anchors written in one config table. Calibrate anchors once against train-group percentiles, sanity-check against the published numbers above, then freeze. A hidden-test group then scores the same whoever else is in the file.
4. **Pillar = weighted mean of its available indicators. Level = weighted mean of available pillars**, weights renormalised when a pillar is missing. Report coverage next to the score.
5. **Cap rule**: if Liquidity or Payment discipline is below 25, the level is capped at 50. A failing pillar cannot be averaged away.
6. **Additive drivers**: contribution of pillar `p` is `w_p * (pillar_p - 50)`, and `level = 50 + sum(contributions)` before the cap. Month-on-month change decomposes exactly: `delta level = sum of w_p * delta pillar_p`, and the same one level down for indicators. That answers "why this score" and "what moved it since last month" with no SHAP.

## 4. Pillars and indicators

The design space. Opening weights are in brackets; the built weights and the subset of indicators that made it are in `scoring.md` sections 2 to 5. `opin` and `opout` are trailing 3-month operating inflow and outflow (section 1 exclusions applied).

**A. Liquidity (25%)**
- Cash buffer days: reconstructed month-end liquid balance (checking + saving) / (`opout` / 91). Anchors 0 -> 0, 13 -> 35, 27 -> 60, 62 -> 85, 120 -> 100.
- Share of the last 3 month-ends with negative group cash, and the depth of the minimum against monthly outflow.
- Balance trend: change in buffer days against 6 months earlier.

**B. Cash generation (25%)**
- Operating margin: (`opin` - `opout`) / `opin`.
- Inflow growth: `opin` against the same window 3 months earlier, and against 12 months earlier when history allows (removes seasonality).
- Inflow volatility: robust coefficient of variation (MAD / median) of monthly inflow over 6 to 12 months.

**C. Payment discipline (20%)**: how the group treats those it owes
- Paydex-style score on payables paid in the window, amount-weighted days beyond due.
- Overdue payables open at `t` / trailing monthly payables (rebuilt from dates).
- Regularity of mandatory payments: months in the last 6 with `salary`, `social_security` and `tax` outflows present when the group has a history of them, and whether the payroll day drifts later. Missing payroll or social security is a late and severe signal.

**D. Collections quality (15%)**: how the group gets paid
- Paydex-style score on receivables collected in the window.
- Overdue receivables open at `t` / trailing monthly issued amount, with extra penalty for the share older than 60 days.
- Customer concentration: top-1 and top-3 share of issued amount over 12 months (invoice counterparties).
- `collection_refund` / collections.

**E. Debt burden (15%)**
- Debt service ratio: (`debt_repayment` + `interest_charge`) / `opin`, trailing 6 months.
- DSCR proxy: trailing 12-month operating net flow / trailing 12-month debt service. Anchors 0.8 -> 10, 1.0 -> 35, 1.25 -> 60, 2.0 -> 90.
- Financing cost: (`fee` + `interest_charge`) / `opout`, and its trend.
- Month 24 only: outstanding / granted on `lineofcredit`, `confirming`, `factoring`; total outstanding / annualised inflow; scheduled instalments from `debt_schedule_config` against inflow.
- A group with no debt products and no debt flows scores neutral-high here (75), not 100: no debt is not proof of capacity.

Pillars C and D need invoices. Without them a group is scored on A, B, E plus the mandatory-payments indicator, and the UI says so.

## 5. Level, trend and state: the six questions

The level answers "who is healthy". The rest comes from the level series, not from new models.

- **Trend**: Theil-Sen slope (median of pairwise slopes) of the level over the trailing 6 months, in points per month. Robust to one outlier month.
- **Sustained move**: two one-sided CUSUMs on the level against its own trailing 12-month median, `S_t = max(0, S_{t-1} + (ref - x_t) - k)` for declines and the mirror for improvements, `k = 0.5 sigma`, alarm at `h = 4 sigma`, sigma from MAD of monthly changes. A single bad month barely moves it; a persistent shift accumulates.
- **Onset month** = last month the alarming CUSUM was at zero. **Anticipation** = months between onset (or alarm) and the month the level itself crosses a tier boundary or a proxy distress event happens. This is the measured "how many months ahead".

| State | Rule | Question |
|---|---|---|
| Healthy | level >= 70, no decline alarm | 1 |
| Improving | upward CUSUM alarm or slope >= +1.5/month over 6 months | 2 |
| Bending | downward CUSUM alarm while level still >= 60 | 3 |
| Bump | month more than 2 robust sigma below trailing median, reverts within 2 months, no alarm | 4 |
| Falling | downward alarm and level < 60 | 4 |
| Not enough data | fewer than 6 active months | |

The monitor raises an alert only on a state transition into Bending, Falling or Improving, and attaches the top two drivers of the move since onset (question 5). Thresholds above are starting values: tune them on train groups for alert rate and stability, then freeze.

## 6. Group aggregation

Sum flows and balances across the companies of a group (after currency conversion), then compute ratios on the totals. Do not average company scores: a large healthy parent would hide nothing and a tiny subsidiary would distort nothing. Additionally compute the same level per company with enough data, and surface the weakest subsidiary and its share of group inflow as an explanation item (EBA indicator on related borrowers).

## 7. Validating without labels

1. **Proxy distress events**, defined on months `t+1..t+6` and never used as features at `t`: group cash goes negative, `opin` drops more than 30% year on year, payables lateness tail doubles, a mandatory payment month is missed, debt service stops while debt remains. Check that the level at `t` rank-orders them (AUC, and event rate by score decile), split **by group**.
2. **Monotonicity**: each indicator sub-score should relate to future events in the expected direction. One that does not is mis-anchored or noise: fix or drop it.
3. **Stability**: month-on-month level changes should be small for most groups (target: median absolute change under 3 points), and alert rate should be a few percent of group-months, not 30%.
4. **Both directions**: confirm Improving groups show better forward outcomes than flat groups at the same level. That is the Northbrook vs Velasco claim, measured.
5. **Ablation on coverage**: score invoice-rich groups with and without pillars C and D; rank correlation should stay high, otherwise transaction-only groups are on a different scale.

Weights can be nudged with a constrained fit against the proxy events (non-negative, sum to 1), but keep them round and defensible. A judge must be able to read the table.

## 8. Open questions

Live list in `brief.md` section 10. Answered since this was written: the generator did plant
trajectories. With the same companies active over 18 or more months, 22 groups' operating inflow
falls below 60% of its first six months and 8 rise above 160%; `GROUP_0220` (94 to 64, bending
alarm four months before the tier moved) and `GROUP_0043` (41 to 81) are the brief's two
examples in the real data.

## 9. Sources

- JPMorgan Chase Institute, cash buffer days: https://www.jpmorganchase.com/institute/all-topics/business-growth-and-entrepreneurship/report-cash-flows-balances-and-buffer-days
- FinRegLab, cash-flow data in small-business underwriting: https://finreglab.org/wp-content/uploads/2023/12/FinRegLab_2019-09-06_Research-Report_Small-Business-Spotlight_The-Use-of-Cash-Flow-Data-in-Underwriting-Credit.pdf
- Mastercard Open Finance, SB cash flow analytics: https://developer.mastercard.com/open-finance-us/documentation/products/small-business/cash-flow-analytics-sb/
- Informa D&B, Spanish payment delays Q4 2025: https://forbes.es/economia/866384/el-retraso-medio-en-los-pagos-de-las-empresas-espanolas-cayo-hasta-1397-dias-al-cierre-de-2025/
- D&B Paydex factsheet: https://www.dnb.co.uk/content/dam/web/data-and-ai/cross/content/paydex-score-factsheet/DnB_Paydex_Score_Factsheet.pdf
- FinHealth Score methodology: https://finhealthnetwork.org/tools/financial-health-score/finhealth-score-methodology/
- EBA/GL/2020/06 loan origination and monitoring, section 8.5: https://www.bde.es/f/webbde/INF/MenuHorizontal/Normativa/guias/EBA-GL-2020-06-EN.pdf
- Embat: https://www.embat.io/en and https://www.fintechfutures.com/venture-capital-funding/embat-lands-30m-series-b-for-european-expansion

Product note from the Embat research: CFO or treasurer of a mid-market multi-entity group is the buyer; Embat already sells debt management and counterparty management modules and has no public financing marketplace. A score-driven working-capital offer attaches to those modules and is new for them. The Collections pillar also scores the group's customers, which is a second product: counterparty risk for the CFO's own receivables.

# How the score is computed

The as-built reference for `src/xray/scoring/`. Every formula, constant and rule below is the one
in the code today; when they disagree, the code is right and this file has a bug. Design
rationale and sources are in `health-score-research.md`; this file is what you read to change
something without breaking something else.

```
panel_group.parquet ─┬─> indicators ─> sub-scores ─> pillars ─> level ─┐        score.py
                     │                                                 ├─> states, trend, compound   trend.py (via monitor.py)
                     │                                                 ├─> jumps, shifts, alerts     monitor.py
                     │                                                 ├─> drivers                   explain.py
                     │                                                 └─> offers, actions           offer.py
                     └─> events (proxy labels, t+1..t+6) ─> validate.py
                                                       serve.py  ─> data/serving/*.parquet
                                                       submit.py ─> predictions_*.csv from any CSV directory
```

| Do this | Run |
|---|---|
| Rebuild the level | `make score` (`python -m xray.scoring.score`) |
| Measure it | `make validate` |
| Rebuild the alert feed | `make monitor` |
| Write every serving table | `make serve` |
| Score a hidden-test dump | `make submit RAW=path/to/csvs` |
| Feed the dump month by month, publishing after each | `make replay [FROM=2025-01] [PAUSE=8] [CHANNEL=slack] [CHECK=1]` |
| Everything that must pass before a push | `make ci` |

No `uv` on the machine: `docker run --rm -v "$PWD/data:/app/data" -v "$PWD/src:/app/src"
-e XRAY_PROCESSED_DIR=/app/data/processed -e XRAY_MARTS_DIR=/app/data/marts -w /app xray:latest
python -m xray.scoring.score` runs the same thing (`make docker-build` first).

## 0. Five invariants

Anything you add must keep these. Each has a test or a measurement behind it.

1. **No future data.** A row for month `t` reads panel columns of months `<= t` only. Rolling
   windows are trailing. `balances.csv` reaches earlier months only through the roll-back in
   `pipeline/cash.py`, which recovers the balance that stood at `t` (see `architecture.md` 5).
2. **No population statistics.** No percentile, z-score, rank or mean across groups enters a
   score. Anchors are constants. This is what makes a hidden-test group score the same whoever
   else is in the file: `tests/scoring/test_submit.py::test_a_group_scores_the_same_alone_as_in_a_portfolio`,
   and measured on 70 real groups cut from the raw CSVs, 0 of 1,074 group-months differ.
3. **Nothing is fitted.** There is no training step and no model file. Weights and anchors were
   chosen by reading `make validate` and are then frozen constants. With ~244 labelled groups a
   fit would memorise them.
4. **The level is additive.** `level_uncapped = 50 + sum(contrib_<pillar>)`, exactly. So the
   month-on-month change of the level is exactly the sum of the pillar delta contributions.
   `tests/scoring/test_explain_offer.py::test_delta_contributions_sum_to_the_level_change`.
5. **Missing is not zero.** An indicator a group has no basis for is `NaN`, and the weights
   renormalise around it. A group without invoices has no payment discipline or collections
   pillar, and `coverage` says how much of the weight was available.

## 1. Input: the panel

`data/marts/panel_group.parquet`, one row per `(group_id, month)`, built by `pipeline/panel.py`.
`score()` keeps rows with `is_covered` (at least one transaction that month) and reads these
columns. The company panel has the same columns keyed by `company_id`, and `score(panel,
key="company_id")` scores it identically.

| Column | What it is |
|---|---|
| `cash` | Reconstructed month-end balance of checking and saving accounts, summed over the group. Null when the group has no cash account |
| `inflow_op`, `outflow_op` | Operating money in and out that month. Excludes `transfer`, `investment_*`, `cash_settlement`, `cash_withdrawal`, `debt_repayment`, `interest_charge` |
| `opin_12m` | Trailing 12-month sum of `inflow_op` |
| `debt_service_12m` | Trailing 12-month sum of `debt_repayment_outflow + interest_outflow` |
| `ap_paid`, `ar_collected` | Payables paid and receivables collected that month, by amount |
| `ap_late_days`, `ar_late_days` | Sum over those settled invoices of `amount * max(days paid after due, 0)` |
| `ap_overdue_90d`, `ar_overdue_90d` | Open at month end, past due, and due within the last 90 days |
| `has_erp` | The group had issued an invoice by this month |
| `months_observed`, `n_companies` | Carried through to the output |

Windows below are in **covered months**: a group with a gap in coverage has the gap skipped, not
zero-filled.

## 2. Indicators (`score.indicators`)

Nine raw ratios. `_ratio(a, b)` is `a / b` when `b > 0`, else `NaN`. `sum_k(x)` and `mean_k(x)` are
trailing sums and means over the last `k` covered months of the group, `min_periods` as stated.

| Indicator | Formula | Windows | Why this shape |
|---|---|---|---|
| `buffer_days` | `mean_3(cash) / (mean_3(outflow_op) / 30.42)` | `min_periods=1` | Days of operating outflow the cash covers. Both sides averaged so one lumpy month moves it by a third. The denominator is a mean, not `opout_3m / 91`, so the first months are not inflated by a partial window |
| `negative_cash_share` | share of the last 3 months with `cash < -1.0` | `min_periods=1` | `-1.0`, not `< 0`: an emptied account reconstructs to `+-1e-10` depending on summation order |
| `op_margin` | `(sum_6(inflow_op) - sum_6(outflow_op)) / sum_6(inflow_op)` | `min_periods=1` | Monthly margins swing several-fold; six months is where the median month-on-month move of this indicator falls under 5 points |
| `inflow_growth` | `mean_3(inflow_op) / mean_12(inflow_op)` | `min_periods=1` | Run rate against the trailing year. Ratio indicators cannot see a business shrinking proportionally; this one can. Near 1 until history accrues |
| `ap_days_late` | `sum_3(ap_late_days) / sum_3(ap_paid)` | `min_periods=1` | Amount-weighted days beyond due on payables paid in the window. A ratio of sums, not a mean of monthly ratios, so a month with nothing paid does not distort it |
| `ap_overdue_months` | `ap_overdue_90d / (sum_3(ap_paid) / 3)` | `min_periods=1` | Overdue payables in months of the paid flow. The open-book ratio `ap_overdue / ap_open` was dropped: unpaid rows never close in this dataset, so it drifts towards 1 for every group |
| `ar_days_late` | `sum_3(ar_late_days) / sum_3(ar_collected)` | `min_periods=1` | Same on the receivable side |
| `ar_overdue_months` | `ar_overdue_90d / (sum_3(ar_collected) / 3)` | `min_periods=1` | |
| `debt_service_ratio` | `debt_service_12m / opin_12m` | panel columns | Share of the year's operating inflow that went to debt service |

Then `out.loc[~has_erp, INVOICE_INDICATORS] = NaN`: the four invoice indicators are absent, not
zero, for a group without an ERP.

Every indicator is available from a group's first covered month (`min_periods=1`). A pillar that
joined later would move the level for a reason that is not the group's: the level is a
renormalised mean, so a pillar arriving below the others reads as a decline. Making the basis
complete from month one took real-data stability from 2.68 to 2.45 points and held-out AUC from
0.906 to 0.910.

Constants: `CASH_WINDOW_MONTHS = 3`, `NEGATIVE_CASH_WINDOW = 3`, `LATENESS_WINDOW_MONTHS = 3`,
`MARGIN_WINDOW_MONTHS = 6`, `MARGIN_MIN_MONTHS = 1`, `GROWTH_SHORT_MONTHS = 3`,
`GROWTH_LONG_MONTHS = 12`, `GROWTH_MIN_MONTHS = 1`, `DAYS_PER_MONTH = 365 / 12`,
`OVERDRAWN_BELOW = -1.0`. All in `score.py`.

## 3. Sub-scores (`score.sub_scores`, `anchors.ANCHORS`)

Each indicator maps to 0-100 through a piecewise-linear curve, `numpy.interp` over the anchor
points, clamped to the first and last score outside the range. `NaN` stays `NaN`.

`ANCHORS` is `indicator -> (pillar, weight within pillar, [(raw, score), ...])`, raw values
ascending:

| Indicator | Pillar | Weight in pillar | Curve (raw -> score) |
|---|---|---|---|
| `buffer_days` | liquidity | 0.70 | 0->0, 13->35, 27->60, 62->85, 120->100 |
| `negative_cash_share` | liquidity | 0.30 | 0->100, 0.34->50, 0.67->20, 1->0 |
| `ap_overdue_months` | payment_discipline | 0.50 | 0->100, 0.5->85, 1.5->65, 4->40, 10->20, 25->5 |
| `ap_days_late` | payment_discipline | 0.50 | 0->100, 5->80, 15->60, 30->40, 60->15, 90->0 |
| `op_margin` | cash_generation | 0.60 | -0.50->0, -0.20->25, 0->50, 0.15->75, 0.40->100 |
| `inflow_growth` | cash_generation | 0.40 | 0.5->0, 0.8->30, 1.0->55, 1.25->80, 1.6->100 |
| `ar_overdue_months` | collections | 0.50 | 0->100, 0.5->85, 1.5->65, 4->40, 10->20, 25->5 |
| `ar_days_late` | collections | 0.50 | 0->100, 7->80, 20->60, 40->40, 75->15, 110->0 |
| `debt_service_ratio` | debt_burden | 1.00 | 0->75, 0.05->65, 0.12->50, 0.20->30, 0.35->5 |

The buffer-days anchors are the JPMorgan Chase Institute quartiles (13, 27, 62 days). The
lateness anchors are the D&B Paydex table. Zero debt scores 75, not 100: no debt is not proof of
capacity. The other breakpoints were placed on the percentiles of the 250 groups, checked for
monotonic event rates by quintile, then frozen.

## 4. Pillars (`score.pillars`)

For each pillar, the weighted mean of its indicators that are not `NaN`, weights renormalised:

```
pillar = sum(w_i * s_i for available i) / sum(w_i for available i)
```

`NaN` when no indicator of the pillar is available. Five pillars: `liquidity`,
`payment_discipline`, `cash_generation`, `collections`, `debt_burden`.

## 5. Level (`score.level`, `anchors.PILLAR_WEIGHTS`)

```
PILLAR_WEIGHTS = liquidity 0.40, payment_discipline 0.20, cash_generation 0.20,
                 collections 0.10, debt_burden 0.10

coverage        = sum(W_p for available p)
w'_p            = W_p / coverage                          renormalised weight
contrib_p       = w'_p * (pillar_p - 50)                  0 for an absent pillar
level_uncapped  = 50 + sum(contrib_p)
is_capped       = (liquidity < 25 or payment_discipline < 25) and level_uncapped > 50
level           = 50 if is_capped else level_uncapped
tier            = healthy if level >= 70, coping if >= 40, else vulnerable
```

The cap is the CAMELS rule: a failing liquidity or payment pillar cannot be averaged away. It
bites on 0.7% of group-months. `CAP_PILLARS`, `CAP_PILLAR_SCORE = 25`, `CAP_LEVEL = 50`,
`TIER_BOUNDS` are in `anchors.py`.

Output of `score()`: keys, the nine raw indicators, the nine `<indicator>_score` columns, the
five pillar columns, `level_uncapped`, `is_capped`, `level`, `coverage`, `tier`, five
`contrib_<pillar>` columns, plus `months_observed`, `has_erp`, `n_companies` from the panel.
Indicator and pillar names are disjoint on purpose: `debt_burden` is always the pillar,
`debt_service_ratio` the indicator.

### Worked example: GROUP_0220, August 2026

| Indicator | Raw | Sub-score | Pillar | Pillar score | w' | Contribution |
|---|---|---|---|---|---|---|
| `buffer_days` | 28.3 days | 60.9 | liquidity | 0.7*60.9 + 0.3*100 = **72.7** | 0.40 | +9.06 |
| `negative_cash_share` | 0.00 | 100.0 | | | | |
| `ap_overdue_months` | 1.68 | 63.2 | payment_discipline | **76.2** | 0.20 | +5.24 |
| `ap_days_late` | 2.7 days | 89.2 | | | | |
| `op_margin` | -0.18 | 27.4 | cash_generation | 0.6*27.4 + 0.4*70.7 = **44.7** | 0.20 | -1.05 |
| `inflow_growth` | 1.16 | 70.7 | | | | |
| `ar_overdue_months` | 1.64 | 63.6 | collections | **81.8** | 0.10 | +3.18 |
| `ar_days_late` | 0.0 days | 99.9 | | | | |
| `debt_service_ratio` | 0.003 | 74.5 | debt_burden | **74.5** | 0.10 | +2.45 |

`level_uncapped = 50 + 9.06 + 5.24 - 1.05 + 3.18 + 2.45 = 68.88`, no cap, tier `coping`. The
one pillar under 50 is cash generation: the group has been running a negative six-month margin,
and that is the first-ranked action for it in `actions.parquet`.

## 6. Trajectory: smoothed level, trend, state (`trend.states`)

Runs per group on its level series, sorted by month, one row per covered month. Everything is
causal: the row at `t` uses `level[:t+1]`.

```
smoothed   = EWMA(level, alpha=0.4, adjust=False)            causal, ~1.5 months of lag
for t:
    if t + 1 < 6:  state = not_enough_data, trend = NaN; continue
    sigma      = max(1.4826 * MAD(diff(smoothed[:t+1])), 1.0)
    reference  = median(smoothed[max(0, t-12) : t])          trailing 12 months, excluding t
    deviation  = clip((reference - smoothed[t]) / sigma, -2, 2)
    S_down     = max(0, S_down + deviation - 0.75)           one-sided CUSUM, downward
    S_up       = max(0, S_up   - deviation - 0.75)           mirror, upward
    trend      = Theil-Sen slope of smoothed[t-5 : t+1]      median pairwise slope, points/month
    if trend <= -1.5: S_up = 0                             clear an opposing alarm on reversal
    if trend >=  1.5: S_down = 0
    zero_down  = t if S_down == 0 else zero_down             last month the CUSUM was at zero
    zero_up    = t if S_up   == 0 else zero_up
    down       = S_down > 4 or (down and S_down > 0)         latched until back at zero
    up         = S_up   > 4 or (up   and S_up   > 0)

    if down or trend <= -1.5:      state = falling if smoothed[t] < 60 else bending;  onset = zero_down + 1 if down else t - 5
    elif up or trend >= 1.5:       state = improving;  onset = zero_up + 1 if up else t - 5
    elif smoothed[t] >= 70:        state = healthy
    elif smoothed[t] >= 40:        state = stable
    else:                          state = weak
compound = clip(smoothed + 4 * trend, 0, 100)                 monitor.detect
```

`onset_idx` is the month the alarm started building; it is what the alert's "since <month>" and
its driver attribution are measured from. Constants: `MIN_HISTORY_MONTHS = 6`,
`SMOOTHING_ALPHA = 0.4`, `MIN_SIGMA_POINTS = 1.0`, `CUSUM_REF_MONTHS = 12`,
`CUSUM_SLACK_SIGMAS = 0.75`, `CUSUM_ALARM_SIGMAS = 4.0`, `DEVIATION_CLIP_SIGMAS = 2.0`,
`TREND_ALARM_SLOPE_POINTS = 1.5`, `BENDING_LEVEL = 60`, `HEALTHY_LEVEL = 70`, `WEAK_LEVEL = 40`,
`COMPOUND_HORIZON_MONTHS = 4`.

What the trend is and is not, measured (`brief.md` 9, `status.md` P2): a description of where
the group has been going over six months, robust to one outlier month. It does **not** add
forward-risk discrimination over the level (falling groups in the middle of the level band are
not more likely to go cash-negative), and `level + k * trend` forecasts the level four months out
worse than the level alone for any `k`. Anticipation is therefore measured on the level series
itself: for the 11 groups that first went cash-negative after six clean months, the smoothed
level was 5 points under its running peak a median 7 months before, and the CUSUM alarm fired a
median 6 months before on 73% of them.

## 7. Monitor (`monitor.detect`)

Two detectors over the scored series, both causal, writing `trajectory` and `alerts`.

- **Jump**: one month's change of the *raw* level beyond `max(10 points, 3 * sigma)` where sigma
  is `robust_sigma` of the group's prior monthly changes (at least 4 of them). Fires with no
  delay. Published provisional, then resolved two months later as `sustained` (the state machine
  is alarming in the same direction) or `reverted` (half or more of the move came back).
- **Shift**: the state machine enters a `down` alarm (`bending`/`falling`) or an `up` alarm
  (`improving`) from no alarm or from the other direction. `bending -> falling` is not an alert:
  it is the same decline crossing a level line.

Each alert row carries `onset_month`, `level_at_onset`, `level_at_alert`, `driver_1`/`driver_2`
(the two pillars whose `contrib_*` moved most between onset and the alert, in the alarm's
direction), `tier_change_month` and `anticipation_months` (hindsight columns for the validation
view, never for a message sent at `t`), and `severity` (`|delta| * inflow percentile`, a ranking
key). Full detail in the module docstring.

## 8. Explanation (`explain.drivers`, `explain.indicator_drivers`)

`drivers(scores)` melts the score table to one row per `(group_id, month, pillar)` with `score`,
`contribution`, the pillar's `headline` raw indicator (`HEADLINES`: buffer_days, op_margin,
ap_days_late, ar_days_late, debt_service_ratio) and `delta_score`, `delta_contribution` against
the previous covered month. Absent pillars have no row. By invariant 4,
`sum(delta_contribution) over pillars == level_uncapped[t] - level_uncapped[t-1]`.

`indicator_drivers(scores)` is the same one level down: `(group_id, month, pillar, indicator,
raw, score, delta_score)`. It is not in the serving tables yet; use it when the UI needs "which
indicator inside the pillar".

## 9. Offer and actions (`offer.offers`, `offer.actions`)

```
eligible          = compound >= 40 and state != not_enough_data
limit_eur         = monthly_inflow_eur * interp(compound, [40, 90] -> [0.2, 1.5]), 0 if not eligible, rounded to 1,000
apr               = interp(compound, [40, 90] -> [0.125, 0.045]), NaN if not eligible
limit_change_eur  = limit_eur - previous month's limit_eur
```

`monthly_inflow_eur = opin_3m / 3`, attached by `serve._with_panel`. It is real euros: every
amount is converted in `xray.pipeline.clean` at the average rate of its year (see
`architecture.md`, data traps).

Actions: at each group's last scored month, the three available pillars with the lowest
`contrib_*`, one sentence each from `ACTIONS`, with
`expected_level_gain = 0.4 * max(70 - pillar, 5) * W_p / coverage`: the contribution the pillar
would recover by closing 40% of its gap to 70, in level points.

## 10. Serving and submission

`serve.build()` scores the group panel, attaches `monthly_inflow_eur` and `dscr`
(`(opin_12m - opout_12m) / debt_service_12m`), runs `monitor.detect`, then `serve.publish()`
swaps the tables of `serving-contract.md` into `data/serving` and stamps `_version.json`.
`serve.assemble()` is the same from in-memory panels, which is what the replay uses.
`groups.name` is the `group_id`; the dataset has no names.

`pipeline/replay.py` feeds the dump through the whole chain one month at a time (lake, rebuild
as-of, publish, notify) so the product can be watched moving. It relies on every step above
being causal and unfitted: the score a month gets during the replay is the score it has in the
full run, and `make replay CHECK=1` asserts that on the real data.
`company_scores` uses `score(panel_company, key="company_id")` for every covered month, followed
by the same monitor and pillar explanation as the group series. `companies` holds names and the
last month's level and operating inflow share. `company_impact` recomputes the group without
each company; positive points mean the company lowers the group score. It is unavailable when
the remaining companies lack coverage or their available pillars differ.

`submit.predict(raw_dir)` runs clean -> cash -> panel -> score -> detect over any directory
holding the nine CSVs, in a temporary directory, and returns `groups` (`group_id, month, level,
level_smooth, trend, compound, state, tier, coverage, months_observed`) and `companies`
(`company_id, group_id, month, level, tier, coverage`). `make submit RAW=dir` writes them as CSV.
Long form on purpose: the organisers' format is not published (`brief.md` Q1); cut whatever
they ask for from these.

## 11. Validation (`events.py`, `validate.py`)

There is no label in the data, so `events.build` manufactures forward-looking proxies per
group-month over `t+1..t+6`: `cash_negative` (group cash below zero in any of those months),
`missed_payroll` (a month with no salary outflow after at least three paydays),
`inflow_collapse` (`opin_3m` under half of its value at `t`), `distress = cash_negative or
missed_payroll`. The last six months of every group carry no label. These columns are a ruler
and must never become a feature.

`make validate` prints four blocks, split by **group** (30% held out, seed 2026):

1. **Discrimination**: AUC of the level against each event, train and held out, plus the event
   rate by level quintile. Today: `cash_negative` 0.910 held out (0.878 train), quintiles 51.6%
   -> 0.6%. `missed_payroll` 0.593 and `inflow_collapse` 0.392 are not readable from the trail.
2. **Trajectory**: event rate by 6-month Theil-Sen trend bucket. Today it shows the trend is not
   a second predictor (section 6).
3. **Stability**: median and p90 of the month-on-month level change. Today 2.45 and 9.27,
   target under 3 on the median.
4. **Ablation**: held-out AUC with each pillar dropped. Today only liquidity (-0.362) and debt
   burden (-0.008) cost AUC when removed; payment discipline, collections and cash generation
   each add +0.002 to +0.018 when dropped. They are kept for what they explain.

## 12. Changing things

Every recipe ends with the same check: `make score && make validate`, read blocks 1 and 3, then
`make ci`. If `data/serving` is what the demo reads, `make serve` after.

**Change a weight or an anchor.** Edit `anchors.py` only. Nothing else references the numbers.
Keep the curves monotonic and written with raw values ascending; `sub_scores` interpolates and
clamps, so a curve that doubles back scores nonsense silently.

**Change a window.** The constants at the top of `score.py`. Longer windows: calmer level, later
detection. The stability target is a median month-on-month change under 3; the last time the
6-month margin window was tested against 3 months it took that indicator's median move from 8.4
to about 5 points at no AUC cost, and 12 months bought nothing more.

**Add an indicator.** Four edits, in this order:
1. If it needs a panel column that does not exist, add it to `pipeline/panel.py` (`_ADDITIVE`
   plus the SQL) with a test in `tests/pipeline/test_panel.py`. Additive columns only: ratios
   are computed after the group roll-up so a group's DSO is weighted by amount, not by
   subsidiary count. Rebuild with `make panel`.
2. Compute the raw value in `score.indicators` as a `_ratio` of trailing sums or means. `NaN`
   when there is no basis. If it needs invoices, add it to `INVOICE_INDICATORS`.
3. Add its row to `ANCHORS` with a pillar and a within-pillar weight; rebalance the other weights
   in that pillar to sum to 1. To place the breakpoints, print its quantiles on the 250 groups and
   its `cash_negative` rate by quintile (there is a pattern for this at the bottom of
   `validate.py`'s spirit: `pd.qcut` on the raw value, `groupby` the event); the rate must be
   monotone in the direction you expect, or the indicator is noise or mis-signed.
4. Add its raw name to `explain.HEADLINES` if it should be the pillar's headline, and to the
   `_panel()` fixture in `tests/scoring/test_score.py`.

**Add a pillar.** As above, plus a weight in `PILLAR_WEIGHTS` (all weights sum to 1), a
sentence in `offer.ACTIONS`, a headline in `explain.HEADLINES`, and the name in
`export_serving.VALID_PILLARS` so the front end export accepts it. Decide whether it joins
`CAP_PILLARS`.

**Change the state machine or the alarm thresholds.** `trend.py`. Then `make monitor` and read
the alert rate (today 8.3% of group-months, about 18 a month on 250 groups), the share of alerts
landing before the tier moves (50%), and the late share (`status.md` P9). The level is calmer
than when `SMOOTHING_ALPHA = 0.4` was chosen, so the alpha can move towards 1 (`status.md` N4).

**Change what an event means.** `events.py`. Then re-read every number in `status.md`: the
anchors were placed against `cash_negative`.

## 13. Tried and dropped

So nobody spends the afternoon on it again. All measured against forward `cash_negative` on
held-out groups unless stated.

| Idea | Result |
|---|---|
| EWMA on the pillar contributions inside the level (alpha 0.3 to 0.5) | Stability 1.5 to 1.9, AUC unchanged, drivers stay additive. Not adopted because `trend.py` already smooths and the two would compound into 3 months of lag. Revisit only together with raising `SMOOTHING_ALPHA` |
| `buffer_trend` (buffer days vs 6 months earlier) as a liquidity indicator | AUC 0.889 -> 0.880, stability worse. The level should be a level; trend lives in `trend.py` |
| `cash_trend` (3-month vs 12-month mean cash) | U-shaped event rate by quintile: both fast-rising and fast-falling cash precede trouble. Not monotone, not anchorable |
| Open-book overdue ratio `ap_overdue / ap_open` | Drifts from 0.08 to 0.83 median across the window for everyone. Replaced by the 90-day overdue over paid flow, AUC 0.652 vs 0.647 and flat over the window |
| Overdue aged under 180 days instead of 90 | AUC the same (0.657), drift half removed instead of fully |
| Dropping the two invoice pillars | Held-out AUC +0.02 on `cash_negative`, but the product cannot explain a number made of cash alone and the hidden metric is unknown. Kept at 0.20 and 0.10 |
| `compound = level + 4 * trend` as a forecast | RMSE against the level four months later is worse than the level alone at every horizon tested (k = 2, 4; raw and smoothed level). Kept as the pricing key because it rewards direction, not because it predicts |
| Trend buckets as an anticipation signal for `cash_negative` | No separation in the middle of the level band. Anticipation is measured on the level series instead |
| 3-month margin and growth (`opin_3m` vs 3 months earlier) | Median month-on-month move 8 to 11 points on those indicators alone; the whole level moved 4. Replaced by 6-month margin and 3-vs-12 run rate |

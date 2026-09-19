# Serving contract

The tables the product reads, one parquet each in `data/serving/`. The API exposes every parquet
there as a DuckDB view with the file's name. The product team builds against this; the model team
writes these same tables when the real score lands.

**They are real.** `make serve` (`src/xray/scoring/serve.py`) writes them from the challenge
dataset: 250 groups, 1,286 companies, 4,114 scored group-months. The dataset has no trading
names, so `groups.name` is the `group_id` and `groups.sector` is null. `make mock`
(`src/xray/scoring/mock.py`) still generates 45 invented groups (`DEMO_001`..`DEMO_045`) with an
`archetype` column for developing against a known story; do not ship them.

The brief's worked example maps onto real groups. `GROUP_0220` is Velasco: 94 in January 2025,
bending alarm in June 2025 at 82 while still in the healthy tier, tier crossed to coping in
October 2025, 64 at month 24. `GROUP_0043` is Northbrook: 41 to 81, improving.

## The compound score

```
level     weighted mean of the available pillars, 0-100, capped at 50 if liquidity or
          payment discipline is under 25. Answers "who is healthy today".
smooth    causal EWMA of the level, alpha 0.4. The raw level swings a median of 4 points a
          month, so everything about trajectory is measured on this instead.
trend     Theil-Sen slope of the smoothed level over the trailing 6 months, points per month.
compound  clip(smooth + 4 * trend, 0, 100): the level projected four months along its trend.
```

`compound` is the single number the product prices and ranks on, because it rewards improving
groups and tightens early on bending ones. `level` stays the number shown as "the score".
Pillar weights: liquidity 40, payment discipline 20, cash generation 20, collections 10, debt
burden 10 (`src/xray/scoring/anchors.py`). Groups without ERP have no payment discipline or
collections pillar; weights renormalise and `coverage` says how much of the full weight was
available.

## Publishing

`serve.publish` writes the tables to `.next/`, moves them over the live ones file by file and
writes `_version.json` last: `build_id`, `built_at`, `as_of` (last month of data the build saw),
`latest_month`, `n_groups`, `n_alerts`, `tables`. The API exposes it as `GET /api/v1/version`
and every table as `GET /api/v1/tables/{name}`, rows as JSON objects with `null` for missing
values and timestamps as ISO strings. The front end polls the version and refetches the tables
when `build_id` changes; without an API it reads the same tables from `web/public/data/*.json`.

## Tables

`groups`: one row per group.
`group_id`, `name`, `sector`, `country`, `n_companies`, `has_erp`, `annual_revenue_eur`, `archetype` (mock only).

`companies`: subsidiaries at the last month.
`company_id`, `group_id`, `name`, `inflow_share`, `level`, `is_weakest`.

`scores`: one row per group and observed month. Groups onboard at different months, as in the real data.

| Column | |
|---|---|
| `group_id`, `month` | Keys. `month` is the first day of the month, 2024-09 to 2026-08 |
| `liquidity`, `cash_generation`, `payment_discipline`, `collections`, `debt_burden` | Pillar scores 0-100, null when the pillar is unavailable |
| `level`, `level_uncapped`, `is_capped`, `coverage` | The score and its cap rule |
| `level_smooth`, `trend`, `compound` | See above. `trend` is null under 6 months of history |
| `state` | `healthy`, `stable`, `weak`, `improving`, `bending`, `falling`, `not_enough_data`. A bump is no longer a state: it is how a jump alert resolves |
| `tier` | `healthy` >= 70, `coping` 40-70, `vulnerable` < 40 |
| `months_observed` | Months of history so far |
| `buffer_days`, `operating_margin`, `ap_days_beyond_terms`, `ar_days_beyond_terms`, `dscr` | Headline indicator behind each pillar, for the explanation copy |
| `monthly_inflow_eur` | Operating inflow, sizes the offer |

`drivers`: one row per group, month and available pillar. Additive: `level_uncapped = 50 + sum(contribution)`
and the month-on-month change of the level is `sum(delta_contribution)`.
`group_id`, `month`, `pillar`, `score`, `contribution`, `delta_score`, `delta_contribution`.

`alerts`: the monitor's feed, one row per moment worth a message. Written by
`xray.scoring.monitor` over the scores; `xray.scoring.notify` turns a row into the text that
goes to Slack or email.

Two kinds, because a spike and a slide are different questions:

| `kind` | Raised when | Latency |
|---|---|---|
| `jump` | one month of the **raw** level moves more than `max(10 points, 3 sigma)` of that group's own monthly swing | none, and provisional |
| `shift` | the CUSUM on the **smoothed** level enters a down or an up alarm | slower, only fires on a move that held |

A jump reports the raw level, a shift the smoothed one, so the three level columns of a row
always agree with each other. An alarm already raised is not raised again: `bending` to
`falling` is the same decline crossing a line. The other half of a spike is suppressed too, and
covered by the first jump's revert message instead.

| Column | |
|---|---|
| `group_id`, `month` | Keys. One group can have several alerts in a month only if they are different kinds |
| `kind` | `jump` or `shift` |
| `direction` | `down` or `up`. Improvement is a first-class alert, not an afterthought |
| `state_from`, `state_to` | The state either side of the alert month |
| `onset_month` | Where the move started: the month the CUSUM last sat at zero, or the month before a jump |
| `level_at_onset`, `level_at_alert`, `delta_level` | The move, on the series its detector measured |
| `trend`, `compound` | Slope in points per month at the alert, and the four-month projection |
| `tier` | Tier at the alert month |
| `driver_1`, `driver_2` | Pillars whose contribution moved most since onset, worst first |
| `sigmas` | Size of a jump in that group's own monthly swings. Null for a shift |
| `resolution`, `resolution_month` | `sustained`, `reverted` (a bump) or `open`, and the month it became knowable, two months after the jump. Empty for a shift |
| `monthly_inflow_eur` | Operating inflow at the alert month |
| `severity` | Ranking key only: `abs(delta_level)` weighted by the group's inflow percentile in the portfolio. Not money: inflow is summed across currencies without conversion |
| `tier_change_month`, `anticipation_months`, `late` | **Hindsight.** Months from the alert to the next tier change, and whether the tier had already moved before the alert. For the validation view; never put them in a message |

Everything except those last three is causal: the row dated `t` is what the system would have
raised at the end of `t`. That is what lets the demo replay the feed month by month.

`offers`: working-capital line, repriced every month from `compound`.
`group_id`, `month`, `eligible` (compound >= 40 and enough history), `limit_eur` (0.2x to 1.5x
monthly inflow), `apr` (12.5% down to 4.5%), `limit_change_eur`.

`actions`: three ranked moves per group at its last month.
`group_id`, `month`, `rank`, `pillar`, `action`, `expected_level_gain`.

### `payers` (read by the Customers agent, not exported to the page)

One row per group, month and customer, written by `xray.scoring.payers` (`make serve`). Built from
the group's own receivable invoices as of each month: open and overdue are rebuilt from dates,
`status` and `pending_amount` are never read. Kept: the 12 largest customers by billing plus the
5 with the most overdue. Only groups with an ERP have rows.

| Column | Meaning |
|---|---|
| `counterparty_id`, `name` | the customer; `name` is an alias, ids do not link to `companies` |
| `billed_12m_eur`, `share_of_billing` | billing over the last twelve months and its share of the group's |
| `open_eur`, `overdue_eur`, `oldest_overdue_days` | unpaid as of the month, the part past due, the oldest of it |
| `n_paid`, `reliable` | paid invoices so far; reliable from 6 |
| `days_late`, `days_late_change` | amount-weighted days beyond terms over six months, and against the six before |
| `payer_score` | 100, minus 1.5 per day late (capped at 60 days), minus up to 10 for overdue exposure |

Amounts arrive in euros from `xray.pipeline.clean`, at the average rate of the invoice's year.

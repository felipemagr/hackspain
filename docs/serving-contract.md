# Serving contract

The tables the product reads, one parquet each in `data/serving/`. The API exposes every parquet
there as a DuckDB view with the file's name. The product team builds against this; the model team
writes these same tables when the real score lands.

**Today they are invented.** `make mock` (`src/xray/scoring/mock.py`) generates 45 made-up groups
(`DEMO_001`..`DEMO_045`) that follow the design in `docs/health-score-research.md`. Nothing is
computed from the challenge dataset. `groups.archetype` records the story each group was
generated to tell; the real engine will not have that column.

`DEMO_001` Northbrook Foods (45 -> 65) and `DEMO_002` Velasco Industrial (82 -> 69) are the brief's
worked example: 4 points apart at month 24, opposite bets, and the compound score ranks them the
other way round (68 vs 64). `DEMO_003` is Cabify (52 -> 70, improving), under its real name so
it matches the public context cached in `data/serving/context/cabify.json`. Its scores are invented too.

## The compound score

```
level     weighted mean of the available pillars, 0-100, capped at 50 if liquidity or
          payment discipline is under 25. Answers "who is healthy today".
trend     Theil-Sen slope of the level over the trailing 6 months, points per month.
compound  clip(level + 4 * trend, 0, 100): the level projected four months along its trend.
```

`compound` is the single number the product prices and ranks on, because it rewards improving
groups and tightens early on bending ones. `level` stays the number shown as "the score".
Pillar weights: liquidity 25, cash generation 25, payment discipline 20, collections 15, debt
burden 15. Groups without ERP have no payment discipline or collections pillar; weights
renormalise and `coverage` says how much of the full weight was available.

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
| `trend`, `compound` | See above. `trend` is null under 6 months of history |
| `state` | `healthy`, `stable`, `weak`, `improving`, `bending`, `falling`, `bump`, `not_enough_data` |
| `tier` | `healthy` >= 70, `coping` 40-70, `vulnerable` < 40 |
| `months_observed` | Months of history so far |
| `buffer_days`, `operating_margin`, `ap_days_beyond_terms`, `ar_days_beyond_terms`, `dscr` | Headline indicator behind each pillar, for the explanation copy |
| `monthly_inflow_eur` | Operating inflow, sizes the offer |

`drivers`: one row per group, month and available pillar. Additive: `level_uncapped = 50 + sum(contribution)`
and the month-on-month change of the level is `sum(delta_contribution)`.
`group_id`, `month`, `pillar`, `score`, `contribution`, `delta_score`, `delta_contribution`.

`alerts`: one row each time a group enters `bending`, `falling` or `improving`. This is the monitor's feed.
`group_id`, `month`, `state_from`, `state_to`, `onset_month`, `level_at_onset`, `level_at_alert`,
`driver_1`, `driver_2` (pillars that moved most since onset), `tier_change_month`,
`anticipation_months` (months between the alert and the tier actually changing; null if it has not).

`offers`: working-capital line, repriced every month from `compound`.
`group_id`, `month`, `eligible` (compound >= 40 and enough history), `limit_eur` (0.2x to 1.5x
monthly inflow), `apr` (12.5% down to 4.5%), `limit_change_eur`.

`actions`: three ranked moves per group at its last month.
`group_id`, `month`, `rank`, `pillar`, `action`, `expected_level_gain`.

# First real score baseline

Run `make score-baseline` after the raw CSVs are in `data/raw`. It builds the monthly panel and writes
`data/marts/real_scores.parquet` and `real_drivers.parquet`. The demo still reads its separate mock
serving tables; this baseline does not replace them.

One row is one business group at one month. The first score requires three observed months, at
least two covered months in the last three, a transaction in the current month, and some explicitly
categorised operating flow. A six-consecutive-month window is required for the trend. Missing
scores and pillars stay null, rather than being imputed.

| Pillar | Starting signal | Weight |
|---|---|---:|
| Liquidity | Reconstructed cash divided by three-month known operating outflow, in days | 25% |
| Cash generation | Known-category operating margin, plus three-month inflow growth when available | 25% |
| Payment discipline | Amount-weighted days past due on payables settled in the last three months | 20% |
| Collections | Amount-weighted days past due on receivables settled in the last three months | 15% |
| Debt burden | Known debt repayments and interest divided by known operating inflow | 15% |

Only `collection`, `bulk_collection`, and `pos_settlement` feed known operating inflow. Only
`payment`, `bulk_payment`, `utility`, `salary`, `social_security`, and `tax` feed known operating
outflow. `uncategorized` is never assigned a category. Its share of total transaction volume is
reported separately as `uncategorized_share`; a high share makes the score less reliable.
`currency_mixed` flags groups whose companies use multiple currencies. The pipeline converts
amounts to euros at the annual rates in `src/xray/pipeline/fx_rates.csv`.

Available pillar weights renormalise to one. The uncapped level is exactly
`50 + sum(weight * (pillar - 50))`; `real_drivers` records every contribution. A liquidity or
payment-discipline pillar below 25 caps the level at 50. Theil-Sen slope over six months is the
trend, and `compound` is `clip(level + 4 * trend, 0, 100)`. The anchors and state thresholds are
provisional. They have not been calibrated against future proxy events or the leaderboard.

The cash pillar uses the panel's back-reconstructed balances only after the first account
movement. It inherits the assumption that the final snapshot and dated account flows are
complete. Mixed-currency groups retain an explicit quality flag beside the converted totals.

# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

FastAPI with a lightweight integrated page. The user asked for something simple to inspect results; no separate frontend is needed for this first surface.

## Users

The hackathon team inspects the real scores calculated for business groups.

## Product Purpose

X Ray turns monthly financial trails into an explainable group health score. This first interface lets the team inspect the calculated results and their data-quality limits.

## Operating Context

The viewer runs locally against precomputed score and driver parquet files. It is separate from the invented `DEMO_*` serving tables used by the product demo.

## Capabilities and Constraints

- Browse 250 groups, including those without a valid latest score.
- Inspect monthly level, trend, pillars, driver contributions, and available headline indicators.
- Show unclassified transaction share and mixed-currency flags.
- Do not infer labels for transactions without a category.
- Present the score as a provisional baseline, not as a calibrated credit rating.

## Evidence on Hand

- `data/marts/real_scores.parquet` and `real_drivers.parquet` hold the calculated results.
- `docs/score-methodology.md` describes the current formulas and unresolved limitations.

## Product Principles

- Distinguish observed values from missing values.
- Keep score quality visible beside the score.
- Make the trajectory and its named drivers inspectable at each month.

"""Explainable monthly health score from the observed group panel."""

import numpy as np
import pandas as pd

from xray.config import MARTS_DIR
from xray.pipeline.lineage import publish

WEIGHTS = {
    "liquidity": 0.25,
    "cash_generation": 0.25,
    "payment_discipline": 0.20,
    "collections": 0.15,
    "debt_burden": 0.15,
}
PILLARS = tuple(WEIGHTS)
MIN_SCORE_MONTHS = 3
MIN_TREND_MONTHS = 6


def _band(value: pd.Series, x: list[float], y: list[float]) -> pd.Series:
    """Map an observed ratio onto fixed 0-100 anchors, preserving missing values."""
    return pd.Series(np.interp(value, x, y), index=value.index).where(value.notna())


def _theil_sen(values: np.ndarray) -> float:
    """Median pairwise monthly slope for six consecutive level observations."""
    i, j = np.triu_indices(len(values), k=1)
    return float(np.median((values[j] - values[i]) / (j - i)))


def _score_group(group: pd.DataFrame) -> pd.DataFrame:
    """Score one group in month order, using only the current and preceding rows."""
    g = group.sort_values("month").copy()
    for col in (
        "operating_inflow",
        "operating_outflow",
        "uncategorized_amount",
        "inflow",
        "outflow",
        "debt_repayment_outflow",
        "interest_outflow",
        "ar_collected",
        "ap_paid",
        "ar_late_days",
        "ap_late_days",
    ):
        g[f"{col}_3m"] = g[col].rolling(3, min_periods=1).sum()

    known_in = g["operating_inflow_3m"]
    known_out = g["operating_outflow_3m"]
    total_volume = g["inflow_3m"] + g["outflow_3m"]
    g["uncategorized_share"] = g["uncategorized_amount_3m"].div(
        total_volume.where(total_volume > 0)
    )
    g["currency_mixed"] = g["n_currencies"] > 1
    margin = ((known_in - known_out) / known_in.where(known_in > 0)).clip(-1, 1)
    margin = margin.where(known_in > 0, -1).where(known_in + known_out > 0)
    growth = (known_in / known_in.shift(3).where(known_in.shift(3) > 0) - 1).clip(-1, 1)
    margin_score = _band(margin, [-0.5, -0.1, 0, 0.1, 0.25], [0, 25, 50, 75, 100])
    growth_score = _band(growth, [-0.5, -0.15, 0, 0.15, 0.5], [0, 35, 60, 80, 100])
    g["cash_generation"] = margin_score.where(
        growth_score.isna(), 0.7 * margin_score + 0.3 * growth_score
    )
    g["operating_margin"] = margin

    buffer_days = g["cash"].div(known_out.where(known_out > 0) / 91)
    cash_valid = g["has_cash"] & ~g["cash_is_extrapolated"] & (known_out > 0)
    g["buffer_days"] = buffer_days.where(cash_valid)
    g["liquidity"] = _band(g["buffer_days"], [0, 13, 27, 62, 120], [0, 35, 60, 85, 100])

    g["ap_days_beyond_terms"] = g["ap_late_days_3m"].div(g["ap_paid_3m"].where(g["ap_paid_3m"] > 0))
    g["ar_days_beyond_terms"] = g["ar_late_days_3m"].div(
        g["ar_collected_3m"].where(g["ar_collected_3m"] > 0)
    )
    late_days = [0, 15, 22, 30, 60, 90, 120]
    late_scores = [80, 70, 60, 50, 40, 30, 20]
    g["payment_discipline"] = _band(g["ap_days_beyond_terms"], late_days, late_scores).where(
        g["has_erp"]
    )
    g["collections"] = _band(g["ar_days_beyond_terms"], late_days, late_scores).where(g["has_erp"])

    debt_service = g["debt_repayment_outflow_3m"] + g["interest_outflow_3m"]
    debt_ratio = debt_service.div(known_in.where(known_in > 0))
    g["debt_burden"] = _band(debt_ratio, [0, 0.1, 0.25, 0.5, 1], [90, 75, 50, 20, 0])
    g["debt_burden"] = g["debt_burden"].where(known_in > 0)

    available = g[list(PILLARS)].notna()
    base_weights = pd.Series(WEIGHTS)
    g["coverage"] = available.mul(base_weights).sum(axis=1)
    weights = available.mul(base_weights).div(g["coverage"].replace(0, np.nan), axis=0)
    contributions = weights.mul(g[list(PILLARS)].fillna(50).sub(50))
    for pillar in PILLARS:
        g[f"contrib_{pillar}"] = contributions[pillar].fillna(0)
    g["level_uncapped"] = 50 + contributions.sum(axis=1)
    enough = (
        g["is_covered"]
        & (g["months_observed"] >= MIN_SCORE_MONTHS)
        & (g["is_covered"].rolling(3, min_periods=1).sum() >= 2)
        & (known_in + known_out > 0)
        & (g["coverage"] > 0)
    )
    g["level_uncapped"] = g["level_uncapped"].where(enough)
    g["is_capped"] = ((g["liquidity"] < 25) | (g["payment_discipline"] < 25)) & (
        g["level_uncapped"] > 50
    )
    g["level"] = g["level_uncapped"].where(~g["is_capped"], 50)

    levels = g["level"].to_numpy(dtype=float)
    slopes = np.full(len(g), np.nan)
    for end in range(MIN_TREND_MONTHS, len(g) + 1):
        window = levels[end - MIN_TREND_MONTHS : end]
        if np.isfinite(window).all():
            slopes[end - 1] = _theil_sen(window)
    g["trend"] = slopes
    g["compound"] = (g["level"] + 4 * g["trend"].fillna(0)).clip(0, 100)
    g["state"] = np.select(
        [
            g["trend"] >= 1.5,
            (g["trend"] <= -1.5) & (g["level"] >= 60),
            g["trend"] <= -1.5,
            g["level"] >= 70,
            g["level"] < 40,
        ],
        ["improving", "bending", "falling", "healthy", "weak"],
        default="stable",
    )
    g.loc[g["trend"].isna(), "state"] = "not_enough_data"
    g["tier"] = pd.cut(
        g["level"],
        [-1, 40, 70, 101],
        right=False,
        labels=["vulnerable", "coping", "healthy"],
    ).astype("string")
    return g


def build(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Build real group scores and additive pillar drivers from the monthly panel."""
    scored = pd.concat(
        [_score_group(group) for _, group in panel.groupby("group_id", sort=False)],
        ignore_index=True,
    )
    score_cols = [
        "group_id",
        "month",
        *PILLARS,
        "level",
        "level_uncapped",
        "is_capped",
        "coverage",
        "uncategorized_share",
        "currency_mixed",
        "trend",
        "compound",
        "state",
        "tier",
        "months_observed",
        "buffer_days",
        "operating_margin",
        "ap_days_beyond_terms",
        "ar_days_beyond_terms",
        "operating_inflow_3m",
    ]
    scores = scored[score_cols].rename(columns={"operating_inflow_3m": "known_inflow_3m"})
    drivers = scored.melt(
        id_vars=["group_id", "month"],
        value_vars=list(PILLARS),
        var_name="pillar",
        value_name="score",
    )
    contributions = scored.melt(
        id_vars=["group_id", "month"],
        value_vars=[f"contrib_{pillar}" for pillar in PILLARS],
        var_name="pillar",
        value_name="contribution",
    )
    contributions["pillar"] = contributions["pillar"].str.removeprefix("contrib_")
    drivers = drivers.merge(contributions, on=["group_id", "month", "pillar"])
    drivers.loc[drivers["score"].isna(), "contribution"] = 0
    drivers = drivers.sort_values(["group_id", "pillar", "month"])
    drivers["delta_score"] = drivers.groupby(["group_id", "pillar"])["score"].diff()
    drivers["delta_contribution"] = drivers.groupby(["group_id", "pillar"])["contribution"].diff()
    return {"scores": scores, "drivers": drivers}


def main() -> None:
    """Read the group panel and publish scores and drivers to the mart."""
    panel = pd.read_parquet(MARTS_DIR / "panel_group.parquet")
    for name, table in build(panel).items():
        publish(f"real_{name}", table, sources=["panel_group"], marts_dir=MARTS_DIR)


if __name__ == "__main__":
    main()

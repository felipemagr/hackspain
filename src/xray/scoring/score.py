"""The level score: panel columns -> indicators -> pillars -> one 0-100 number per group-month.

The chain is deliberately additive so it can be explained without SHAP. Contribution of pillar
`p` is `w_p * (pillar_p - 50)` and `level = 50 + sum(contributions)` before the cap, so a
month-on-month change decomposes exactly into the pillars that moved it.

Weights renormalise over the pillars a group actually has: 39% of companies never issue an
invoice, so the two invoice pillars are simply absent for them and `coverage` records how much of
the weight was available.

The level is the slow half of the score: every flow indicator is a ratio of trailing sums, so a
single lumpy month moves it by a fraction. Direction is measured separately on the level series
by `xray.scoring.trend`, which is why no trend indicator lives here.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from xray.config import MARTS_DIR
from xray.pipeline.lineage import publish
from xray.scoring.anchors import (
    ANCHORS,
    CAP_LEVEL,
    CAP_PILLAR_SCORE,
    CAP_PILLARS,
    PILLAR_WEIGHTS,
    TIER_BOUNDS,
)

logger = logging.getLogger(__name__)

SOURCES = ("panel_group",)

# Windows, in covered months. Monthly operating flows swing several-fold for an ordinary group,
# so margin and lateness are ratios of sums over a window rather than one month's ratio.
CASH_WINDOW_MONTHS = 3
NEGATIVE_CASH_WINDOW = 3
LATENESS_WINDOW_MONTHS = 3
MARGIN_WINDOW_MONTHS = 6
MARGIN_MIN_MONTHS = 3
GROWTH_SHORT_MONTHS = 3
GROWTH_LONG_MONTHS = 12
GROWTH_MIN_MONTHS = 6
DAYS_PER_MONTH = 365 / 12
# Reconstructed cash is a long sum of flows, so an emptied account lands at +-1e-10 rather than
# zero. Overdrawn means below this, not below the sign bit.
OVERDRAWN_BELOW = -1.0

INVOICE_INDICATORS = ("ap_overdue_months", "ap_days_late", "ar_overdue_months", "ar_days_late")


def _ratio(num, den) -> np.ndarray:
    return np.where(den > 0, num / den, np.nan)


def indicators(panel: pd.DataFrame, key: str = "group_id") -> pd.DataFrame:
    """Raw indicator values per entity-month, on the operating-flow columns of the panel.

    Args:
        panel: ``panel_group`` (or ``panel_company``), covered rows only, sorted arbitrarily.
        key: Entity column, ``group_id`` or ``company_id``.

    Returns:
        The panel keys plus one column per indicator in ``ANCHORS``. NaN where a group has no
        basis for that indicator, which the pillar step then renormalises around.
    """
    p = panel.sort_values([key, "month"]).reset_index(drop=True)
    by = p.groupby(key)

    def rolling_sum(col: str, window: int, min_periods: int = 1) -> pd.Series:
        return (
            by[col].rolling(window, min_periods=min_periods).sum().reset_index(level=0, drop=True)
        )

    def rolling_mean(col: str, window: int, min_periods: int = 1) -> pd.Series:
        return (
            by[col].rolling(window, min_periods=min_periods).mean().reset_index(level=0, drop=True)
        )

    out = p[[key, "month"]].copy()
    # Month-end cash is a stock and swings hard month to month, so the buffer uses a 3-month mean
    # over a 3-month mean of daily operating outflow.
    smoothed_cash = rolling_mean("cash", CASH_WINDOW_MONTHS)
    out["buffer_days"] = _ratio(
        smoothed_cash, rolling_mean("outflow_op", CASH_WINDOW_MONTHS) / DAYS_PER_MONTH
    )
    out["negative_cash_share"] = (
        by["cash"]
        .rolling(NEGATIVE_CASH_WINDOW, min_periods=1)
        .apply(lambda w: (w < OVERDRAWN_BELOW).mean(), raw=True)
        .reset_index(level=0, drop=True)
    )
    opin = rolling_sum("inflow_op", MARGIN_WINDOW_MONTHS, MARGIN_MIN_MONTHS)
    opout = rolling_sum("outflow_op", MARGIN_WINDOW_MONTHS, MARGIN_MIN_MONTHS)
    out["op_margin"] = _ratio(opin - opout, opin)
    # Run rate against the trailing year: shrinkage is invisible to ratio indicators otherwise.
    out["inflow_growth"] = _ratio(
        rolling_mean("inflow_op", GROWTH_SHORT_MONTHS),
        rolling_mean("inflow_op", GROWTH_LONG_MONTHS, GROWTH_MIN_MONTHS),
    )
    ap_paid = rolling_sum("ap_paid", LATENESS_WINDOW_MONTHS)
    ar_collected = rolling_sum("ar_collected", LATENESS_WINDOW_MONTHS)
    out["ap_days_late"] = _ratio(rolling_sum("ap_late_days", LATENESS_WINDOW_MONTHS), ap_paid)
    out["ar_days_late"] = _ratio(rolling_sum("ar_late_days", LATENESS_WINDOW_MONTHS), ar_collected)
    out["ap_overdue_months"] = _ratio(p["ap_overdue_90d"], ap_paid / LATENESS_WINDOW_MONTHS)
    out["ar_overdue_months"] = _ratio(p["ar_overdue_90d"], ar_collected / LATENESS_WINDOW_MONTHS)
    out["debt_service_ratio"] = _ratio(p["debt_service_12m"], p["opin_12m"])
    # Cash is reconstructed for every group, so a liquidity indicator is never missing for a
    # reason the group controls. The invoice indicators are: absent ERP means absent pillar.
    out.loc[~p["has_erp"].to_numpy(), list(INVOICE_INDICATORS)] = np.nan
    return out


def sub_scores(raw: pd.DataFrame, key: str = "group_id") -> pd.DataFrame:
    """Map each raw indicator onto 0-100 through its anchor curve."""
    out = raw[[key, "month"]].copy()
    for name, (_, _, curve) in ANCHORS.items():
        xs, ys = zip(*curve, strict=True)
        out[name] = np.interp(raw[name], xs, ys, left=ys[0], right=ys[-1])
        out.loc[raw[name].isna(), name] = np.nan
    return out


def pillars(subs: pd.DataFrame, key: str = "group_id") -> pd.DataFrame:
    """Weighted mean of the available indicators of each pillar."""
    out = subs[[key, "month"]].copy()
    for pillar in PILLAR_WEIGHTS:
        members = {n: w for n, (p, w, _) in ANCHORS.items() if p == pillar}
        block, weights = subs[list(members)], pd.Series(members)
        available = weights * block.notna()
        out[pillar] = (block.fillna(0) * available).sum(axis=1) / available.sum(axis=1).replace(
            0, np.nan
        )
    return out


def level(pil: pd.DataFrame, key: str = "group_id") -> pd.DataFrame:
    """Renormalised weighted level, additive pillar contributions, coverage and the cap rule."""
    names = list(PILLAR_WEIGHTS)
    block = pil[names]
    weights = pd.Series(PILLAR_WEIGHTS)
    available = weights * block.notna()
    coverage = available.sum(axis=1)
    renormalised = available.div(coverage.replace(0, np.nan), axis=0)

    contrib = renormalised * (block.fillna(50) - 50)
    out = pil[[key, "month"]].copy()
    out["level_uncapped"] = 50 + contrib.sum(axis=1)
    out["is_capped"] = (block[list(CAP_PILLARS)] < CAP_PILLAR_SCORE).any(axis=1) & (
        out["level_uncapped"] > CAP_LEVEL
    )
    out["level"] = out["level_uncapped"].where(~out["is_capped"], CAP_LEVEL)
    out["coverage"] = coverage
    out["tier"] = [next(t for bound, t in TIER_BOUNDS if v >= bound) for v in out["level"]]
    return out.join(contrib.add_prefix("contrib_"))


def score(panel: pd.DataFrame, key: str = "group_id") -> pd.DataFrame:
    """Score every covered row of a panel.

    Args:
        panel: ``panel_group`` or ``panel_company`` as written by ``xray.pipeline.panel``.
        key: Entity column, ``group_id`` or ``company_id``.

    Returns:
        One row per covered entity-month: indicators, sub-scores, pillars, level, tier and
        contributions.
    """
    panel = panel[panel["is_covered"]]
    raw = indicators(panel, key)
    subs = sub_scores(raw, key)
    pil = pillars(subs, key)
    lvl = level(pil, key)
    keys = [key, "month"]
    extra = [c for c in ("months_observed", "has_erp", "n_companies", "group_id") if c in panel]
    # Indicator and pillar names are disjoint, so the pillar columns keep their plain names.
    return (
        raw.merge(subs, on=keys, suffixes=("", "_score"))
        .merge(pil, on=keys)
        .merge(lvl, on=keys)
        .merge(panel[keys + [c for c in extra if c != key]], on=keys)
    )


def build(marts_dir: Path = MARTS_DIR) -> pd.DataFrame:
    """Score every covered group-month of the published panel."""
    return score(pd.read_parquet(marts_dir / "panel_group.parquet"))


def main() -> None:
    """Score the panel and publish the table to the mart."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    scores = build()
    publish("scores", scores, sources=list(SOURCES))
    logger.info(
        "level median %.1f, capped %.1f%%, mean coverage %.2f",
        scores["level"].median(),
        100 * scores["is_capped"].mean(),
        scores["coverage"].mean(),
    )


if __name__ == "__main__":
    main()

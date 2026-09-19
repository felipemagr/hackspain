"""The level score: panel columns -> indicators -> pillars -> one 0-100 number per group-month.

The chain is deliberately additive so it can be explained without SHAP. Contribution of pillar
`p` is `w_p * (pillar_p - 50)` and `level = 50 + sum(contributions)` before the cap, so a
month-on-month change decomposes exactly into the pillars that moved it.

Weights renormalise over the pillars a group actually has: 39% of companies never issue an
invoice, so the two invoice pillars are simply absent for them and `coverage` records how much of
the weight was available.
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

NEGATIVE_CASH_WINDOW = 3
CASH_WINDOW_MONTHS = 3
GROWTH_LAG_MONTHS = 3
DAYS_PER_QUARTER = 91.0


def indicators(panel: pd.DataFrame) -> pd.DataFrame:
    """Raw indicator values per group-month, on the operating-flow columns of the panel.

    Args:
        panel: ``panel_group``, one row per group per month, sorted arbitrarily.

    Returns:
        The panel keys plus one column per indicator in ``ANCHORS``. NaN where a group has no
        basis for that indicator, which the pillar step then renormalises around.
    """
    p = panel.sort_values(["group_id", "month"]).reset_index(drop=True)
    by_group = p.groupby("group_id")
    out = p[["group_id", "month"]].copy()

    # Month-end cash is a stock and swings hard month to month. The level has to be calm
    # enough for a trend and a CUSUM to mean anything, so the buffer uses a 3-month mean.
    smoothed_cash = (
        by_group["cash"]
        .rolling(CASH_WINDOW_MONTHS, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
    )
    out["buffer_days"] = np.where(
        p["opout_3m"] > 0, smoothed_cash / (p["opout_3m"] / DAYS_PER_QUARTER), np.nan
    )
    out["negative_cash_share"] = (
        by_group["cash"]
        .rolling(NEGATIVE_CASH_WINDOW, min_periods=1)
        .apply(lambda w: (w < 0).mean())
        .reset_index(level=0, drop=True)
    )
    out["op_margin"] = np.where(
        p["opin_3m"] > 0, (p["opin_3m"] - p["opout_3m"]) / p["opin_3m"], np.nan
    )
    prior_inflow = by_group["opin_3m"].shift(GROWTH_LAG_MONTHS)
    out["inflow_growth"] = np.where(prior_inflow > 0, p["opin_3m"] / prior_inflow, np.nan)
    out["ap_overdue_ratio"] = p["ap_overdue_ratio"]
    out["ap_days_late"] = p["ap_days_late"]
    out["ar_overdue_ratio"] = p["ar_overdue_ratio"]
    out["ar_days_late"] = p["ar_days_late"]
    out["debt_burden"] = np.where(p["opin_12m"] > 0, p["debt_service_12m"] / p["opin_12m"], np.nan)
    # Cash is reconstructed for every group, so a liquidity indicator is never missing for a
    # reason the group controls. The invoice indicators are: absent ERP means absent pillar.
    return out


def sub_scores(raw: pd.DataFrame) -> pd.DataFrame:
    """Map each raw indicator onto 0-100 through its anchor curve."""
    out = raw[["group_id", "month"]].copy()
    for name, (_, _, curve) in ANCHORS.items():
        xs, ys = zip(*curve, strict=True)
        out[name] = np.interp(raw[name], xs, ys, left=ys[0], right=ys[-1])
        out.loc[raw[name].isna(), name] = np.nan
    return out


def pillars(subs: pd.DataFrame) -> pd.DataFrame:
    """Weighted mean of the available indicators of each pillar."""
    out = subs[["group_id", "month"]].copy()
    for pillar in PILLAR_WEIGHTS:
        members = {n: w for n, (p, w, _) in ANCHORS.items() if p == pillar}
        block, weights = subs[list(members)], pd.Series(members)
        available = weights * block.notna()
        out[pillar] = (block.fillna(0) * available).sum(axis=1) / available.sum(axis=1).replace(
            0, np.nan
        )
    return out


def level(pil: pd.DataFrame) -> pd.DataFrame:
    """Renormalised weighted level, additive pillar contributions, coverage and the cap rule."""
    names = list(PILLAR_WEIGHTS)
    block = pil[names]
    weights = pd.Series(PILLAR_WEIGHTS)
    available = weights * block.notna()
    coverage = available.sum(axis=1)
    renormalised = available.div(coverage.replace(0, np.nan), axis=0)

    contrib = renormalised * (block.fillna(50) - 50)
    out = pil[["group_id", "month"]].copy()
    out["level_uncapped"] = 50 + contrib.sum(axis=1)
    out["is_capped"] = (block[list(CAP_PILLARS)] < CAP_PILLAR_SCORE).any(axis=1) & (
        out["level_uncapped"] > CAP_LEVEL
    )
    out["level"] = out["level_uncapped"].where(~out["is_capped"], CAP_LEVEL)
    out["coverage"] = coverage
    out["tier"] = [next(t for bound, t in TIER_BOUNDS if v >= bound) for v in out["level"]]
    return out.join(contrib.add_prefix("contrib_"))


def build(marts_dir: Path = MARTS_DIR) -> pd.DataFrame:
    """Score every covered group-month.

    Args:
        marts_dir: Directory holding ``panel_group.parquet``.

    Returns:
        One row per group-month: indicators, sub-scores, pillars, level, tier and contributions.
    """
    panel = pd.read_parquet(marts_dir / "panel_group.parquet")
    panel = panel[panel["is_covered"]]
    raw = indicators(panel)
    subs = sub_scores(raw)
    pil = pillars(subs)
    lvl = level(pil)
    keys = ["group_id", "month"]
    return (
        raw.merge(subs, on=keys, suffixes=("", "_score"))
        .merge(pil, on=keys, suffixes=("", "_pillar"))
        .merge(lvl, on=keys)
        .merge(panel[keys + ["months_observed", "has_erp", "n_companies"]], on=keys)
    )


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

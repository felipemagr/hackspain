"""Why this score, and what moved it since last month.

The level is additive by construction (`xray.scoring.score`): `level_uncapped = 50 + sum of
contributions`, one contribution per pillar. So the explanation is not a model on top of the
model, it is the same arithmetic written out per pillar, and the month-on-month change of the
level is exactly the sum of the `delta_contribution` column.
"""

import pandas as pd

from xray.scoring.anchors import ANCHORS, PILLAR_WEIGHTS

PILLARS = list(PILLAR_WEIGHTS)
KEYS = ["group_id", "month"]

# Headline raw indicator behind each pillar, the number the UI quotes next to the pillar score.
HEADLINES = {
    "liquidity": "buffer_days",
    "cash_generation": "op_margin",
    "payment_discipline": "ap_days_late",
    "collections": "ar_days_late",
    "debt_burden": "debt_service_ratio",
}


def drivers(scores: pd.DataFrame, key: str = "group_id") -> pd.DataFrame:
    """One row per group, month and available pillar, with its move since the previous month.

    Args:
        scores: Output of ``xray.scoring.score.score``, any order.

    Returns:
        ``group_id, month, pillar, score, contribution, headline, delta_score,
        delta_contribution``. Pillars a group does not have are absent, not null.
    """
    keys = [key, "month"]
    score = scores.melt(keys, PILLARS, "pillar", "score").dropna(subset=["score"])
    contrib = scores.melt(keys, [f"contrib_{p}" for p in PILLARS], "pillar", "contribution")
    contrib["pillar"] = contrib["pillar"].str.removeprefix("contrib_")
    headline = scores.melt(keys, list(HEADLINES.values()), "indicator", "headline")
    headline["pillar"] = headline["indicator"].map({v: k for k, v in HEADLINES.items()})
    out = (
        score.merge(contrib, on=keys + ["pillar"])
        .merge(headline.drop(columns="indicator"), on=keys + ["pillar"])
        .sort_values([key, "pillar", "month"])
    )
    by = out.groupby([key, "pillar"])
    out["delta_score"] = by["score"].diff()
    out["delta_contribution"] = by["contribution"].diff()
    return out.reset_index(drop=True)


def indicator_drivers(scores: pd.DataFrame) -> pd.DataFrame:
    """The same decomposition one level down: each indicator's sub-score and its move.

    Returns:
        ``group_id, month, pillar, indicator, raw, score, delta_score``.
    """
    rows = []
    for name, (pillar, _, _) in ANCHORS.items():
        block = scores[KEYS + [name, f"{name}_score"]].rename(
            columns={name: "raw", f"{name}_score": "score"}
        )
        rows.append(block.assign(pillar=pillar, indicator=name))
    out = pd.concat(rows).dropna(subset=["score"]).sort_values(["group_id", "indicator", "month"])
    out["delta_score"] = out.groupby(["group_id", "indicator"])["score"].diff()
    return out[KEYS + ["pillar", "indicator", "raw", "score", "delta_score"]].reset_index(drop=True)

"""The product on top of the score: a working-capital line and what to do about the drivers.

The offer is repriced every month from the compound score (`xray.scoring.trend`): the level
projected a few months along its trend, so an improving group is offered more and a bending one
is tightened before its level says so. Below ``MIN_COMPOUND`` there is no offer.

Actions are one sentence per pillar, ranked by how much the pillar drags the level. The expected
gain is the additive contribution the pillar would recover if it climbed part of the way to 70,
so it is in the same points as the level and the CFO can add them up.
"""

import numpy as np
import pandas as pd

from xray.scoring.anchors import PILLAR_WEIGHTS

PILLARS = list(PILLAR_WEIGHTS)

MIN_COMPOUND = 40.0
# Limit as a multiple of monthly operating inflow, and APR, both linear in the compound score.
LIMIT_CURVE = ([40, 90], [0.2, 1.5])
APR_CURVE = ([40, 90], [0.125, 0.045])
TARGET_PILLAR = 70.0
# Share of the gap to the target an action is expected to close.
ACTION_RECOVERY = 0.4
MIN_GAP = 5.0
N_ACTIONS = 3

ACTIONS = {
    "liquidity": "Build the cash buffer back: draw the working-capital line before month end "
    "and move idle savings balances into the operating account.",
    "cash_generation": "Operating margin is thin: review the three largest recurring outflows "
    "and reprice or renegotiate the contracts renewing this quarter.",
    "payment_discipline": "Clear the supplier invoices more than 30 days overdue, largest first, "
    "and agree a payment calendar with the top five suppliers.",
    "collections": "Chase the receivables older than 60 days and offer early-payment discount "
    "or factoring on the two largest customers.",
    "debt_burden": "Debt service is heavy against inflows: refinance the short-term facilities "
    "into a longer amortising loan.",
}


def offers(scores: pd.DataFrame) -> pd.DataFrame:
    """Limit and price per group-month.

    Args:
        scores: Rows with ``group_id, month, compound, state, monthly_inflow_eur``.

    Returns:
        ``group_id, month, eligible, limit_eur, apr, limit_change_eur``.
    """
    out = scores[["group_id", "month"]].copy()
    eligible = (scores["compound"] >= MIN_COMPOUND) & (scores["state"] != "not_enough_data")
    factor = np.interp(scores["compound"], *LIMIT_CURVE)
    out["eligible"] = eligible.to_numpy()
    out["limit_eur"] = (
        (scores["monthly_inflow_eur"] * factor).where(eligible, 0).round(-3).to_numpy()
    )
    out["apr"] = np.where(eligible, np.interp(scores["compound"], *APR_CURVE).round(4), np.nan)
    out = out.sort_values(["group_id", "month"])
    out["limit_change_eur"] = out.groupby("group_id")["limit_eur"].diff()
    return out.reset_index(drop=True)


def actions(scores: pd.DataFrame) -> pd.DataFrame:
    """Three ranked moves per group at its last scored month, weakest pillar first."""
    last = scores.sort_values("month").groupby("group_id").tail(1).set_index("group_id")
    rows = []
    for gid, row in last.iterrows():
        contrib = pd.Series({p: row[f"contrib_{p}"] for p in PILLARS if pd.notna(row[p])})
        for rank, pillar in enumerate(contrib.nsmallest(N_ACTIONS).index, start=1):
            gap = max(TARGET_PILLAR - row[pillar], MIN_GAP)
            weight = PILLAR_WEIGHTS[pillar] / row["coverage"]
            rows.append(
                {
                    "group_id": gid,
                    "month": row["month"],
                    "rank": rank,
                    "pillar": pillar,
                    "action": ACTIONS[pillar],
                    "expected_level_gain": round(ACTION_RECOVERY * gap * weight, 1),
                }
            )
    return pd.DataFrame(rows)

"""The product on top of the score: a working-capital line and what to do about the drivers.

The offer is repriced every month from the compound score (`xray.scoring.trend`): the level
projected a few months along its trend, so an improving group is offered more and a bending one
is tightened before its level says so. Below ``MIN_COMPOUND`` there is no offer.

One bad month does not reprice a line. When the raw level falls further in a month than the
group's own noise allows and the state machine has not confirmed a decline, the line holds the
previous month's terms until the jump is confirmed or given back, which is the same window
`xray.scoring.monitor` waits before calling it `sustained` or `reverted`. Nothing is held on the
way up: an improving group is repriced the month it improves.

Actions are one sentence per pillar, ranked by how much the pillar drags the level. The expected
gain is the additive contribution the pillar would recover if it climbed part of the way to 70,
so it is in the same points as the level and the CFO can add them up.
"""

import numpy as np
import pandas as pd

from xray.scoring.anchors import PILLAR_WEIGHTS
from xray.scoring.monitor import (
    BUMP_WINDOW_MONTHS,
    JUMP_FLOOR_POINTS,
    JUMP_MIN_CHANGES,
    JUMP_SIGMAS,
)
from xray.scoring.trend import alarm_direction, robust_sigma

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
# Months a line keeps its terms after an unconfirmed one-month fall. The monitor resolves a jump
# to sustained or reverted after the same window, so the first repriced month is the month the
# answer is in.
HOLD_MONTHS = BUMP_WINDOW_MONTHS

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


def _held(level: np.ndarray, state: np.ndarray) -> np.ndarray:
    """Months whose terms are frozen because the level fell in one month and nothing confirms it.

    Causal, like the detectors it borrows from: month ``t`` reads ``level[:t+1]`` and
    ``state[:t+1]`` only, never the resolution the monitor can publish two months later.

    Args:
        level: Raw level per month, ordered, no gaps.
        state: The trajectory state of the same months.

    Returns:
        One flag per month, true while the line holds the previous month's terms.
    """
    changes = np.diff(level)
    out = np.zeros(len(level), dtype=bool)
    remaining = 0
    for t in range(1, len(level)):
        prior = changes[: t - 1]
        if alarm_direction(state[t]) == "down":
            remaining = 0
            continue
        fell = len(prior) >= JUMP_MIN_CHANGES and changes[t - 1] < -max(
            JUMP_FLOOR_POINTS, JUMP_SIGMAS * robust_sigma(prior)
        )
        if fell:
            remaining = HOLD_MONTHS
        if remaining:
            out[t] = True
            remaining -= 1
    return out


def offers(scores: pd.DataFrame) -> pd.DataFrame:
    """Limit and price per group-month.

    Args:
        scores: Rows with ``group_id, month, level, compound, state, monthly_inflow_eur``.

    Returns:
        ``group_id, month, eligible, limit_eur, apr, limit_change_eur, limit_hold``.
    """
    scores = scores.sort_values(["group_id", "month"])
    out = scores[["group_id", "month"]].copy()
    eligible = (scores["compound"] >= MIN_COMPOUND) & (scores["state"] != "not_enough_data")
    factor = np.interp(scores["compound"], *LIMIT_CURVE)
    out["eligible"] = eligible.to_numpy()
    out["limit_eur"] = (
        (scores["monthly_inflow_eur"] * factor).where(eligible, 0).round(-3).to_numpy()
    )
    out["apr"] = np.where(eligible, np.interp(scores["compound"], *APR_CURVE).round(4), np.nan)

    out["limit_hold"] = np.concatenate(
        [
            _held(g["level"].to_numpy(), g["state"].to_numpy())
            for _, g in scores.groupby("group_id", sort=True)
        ]
    )
    priced = ["eligible", "limit_eur", "apr"]
    out[priced] = out[priced].mask(out["limit_hold"]).groupby(out["group_id"]).ffill()
    out["eligible"] = out["eligible"].astype(bool)

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

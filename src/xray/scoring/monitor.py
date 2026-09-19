"""The monitor: what moved, how sharply, and whether it is worth raising a hand.

Two detectors run over the smoothed level of `scores.parquet`, because a spike and a slide are
different questions and the brief asks both:

- `jump`   one month moves further than this group's own noise allows. Latency zero, but it may
           still turn out to be a bump, so it is published provisional and resolved two months
           later as `sustained` or `reverted`.
- `shift`  the CUSUM state machine of `xray.scoring.trend` enters bending, falling or improving.
           Slower, and it only fires on a move that held.

A structural decline usually shows as a jump first and a shift a month or two later; a bump shows
as a jump that resolves to `reverted` and never becomes a shift. That pair is the answer to
question 4 of the brief, visible in the feed rather than argued in the pitch.

Both detectors are causal, so the table can be replayed month by month: the row dated `t` is what
the system would have raised at the end of `t`. Two columns are the exception and are marked
below, because they are measured after the fact and must never appear in a message sent at `t`.

Writes two tables:
- `trajectory`  per group-month, the smoothed level, trend, compound score and state
- `alerts`      per event, the feed the notifier and the product read
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from xray.config import MARTS_DIR
from xray.pipeline.lineage import publish
from xray.scoring.anchors import PILLAR_WEIGHTS
from xray.scoring.trend import COMPOUND_HORIZON_MONTHS, alarm_direction, robust_sigma, states

logger = logging.getLogger(__name__)

SOURCES = ("scores", "panel_group")

PILLARS = list(PILLAR_WEIGHTS)
CONTRIB_COLS = [f"contrib_{p}" for p in PILLARS]

# Thresholds below were swept over the 250 real groups for alert rate, anticipation and how
# cleanly jumps split into bumps and sustained moves. See `docs/status.md` for the numbers they
# land on. They are frozen: retune only against that same table.
# A jump needs a basis to be surprising against: this many monthly changes before it.
JUMP_MIN_CHANGES = 4
JUMP_SIGMAS = 3.0
# Floor under the sigma rule. Below this a move is not worth a message whatever the group's noise.
JUMP_FLOOR_POINTS = 10.0
# A jump that gives back this much of itself within the window was a bump.
BUMP_WINDOW_MONTHS = 2
BUMP_RECOVERY_SHARE = 0.5
MONTHS_PER_QUARTER = 3

# The feed's schema, also the column order. `sigmas`, `resolution` and `resolution_month` are
# jump-only; `tier_change_month` and `anticipation_months` are measured after the fact.
ALERT_COLUMNS = [
    "group_id",
    "month",
    "kind",
    "direction",
    "state_from",
    "state_to",
    "onset_month",
    "level_at_onset",
    "level_at_alert",
    "delta_level",
    "trend",
    "compound",
    "tier",
    "driver_1",
    "driver_2",
    "sigmas",
    "resolution",
    "resolution_month",
    "monthly_inflow_eur",
    "severity",
    "tier_change_month",
    "anticipation_months",
    "late",
]


def _drivers(g: pd.DataFrame, onset: int, t: int, direction: str) -> tuple[str | None, str | None]:
    """The two pillars that moved the level most between ``onset`` and ``t``, worst first."""
    moved = (g.iloc[t][CONTRIB_COLS] - g.iloc[onset][CONTRIB_COLS]).astype(float)
    moved.index = PILLARS
    moved = moved.dropna()
    ranked = (moved.nsmallest(2) if direction == "down" else moved.nlargest(2)).index.tolist()
    ranked += [None, None]
    return ranked[0], ranked[1]


def _anticipation(g: pd.DataFrame, onset: int, t: int) -> tuple[pd.Timestamp, float, bool]:
    """How far ahead of the tier the alert was, the measurement behind judging block two.

    The tier is what a snapshot of the score would have noticed. Hindsight, both columns: they
    are for the validation view and must never be used in a message sent at ``t``.

    Returns:
        The month the tier next changes, the months between the alert and it, and whether the
        tier had already moved between onset and the alert, which makes the alert a late one.
    """
    tier = g["tier"].to_numpy()
    crossed = [k for k in range(t + 1, len(g)) if tier[k] != tier[t]]
    late = bool(tier[t] != tier[onset])
    if not crossed:
        return pd.NaT, np.nan, late
    return g["month"].iat[crossed[0]], float(crossed[0] - t), late


def _resolution(g: pd.DataFrame, t: int) -> tuple[str, pd.Timestamp]:
    """Did the jump at ``t`` hold? Knowable only ``BUMP_WINDOW_MONTHS`` later, hence the month."""
    end = t + BUMP_WINDOW_MONTHS
    if end >= len(g):
        return "open", pd.NaT
    level = g["level"].to_numpy()
    size = level[t] - level[t - 1]
    recovered = any(
        (level[k] - level[t - 1]) * np.sign(size) <= BUMP_RECOVERY_SHARE * abs(size)
        for k in range(t + 1, end + 1)
    )
    held = alarm_direction(g["state"].iat[end]) == ("down" if size < 0 else "up")
    return ("reverted" if recovered and not held else "sustained", g["month"].iat[end])


def _row(g: pd.DataFrame, t: int, onset: int, kind: str, direction: str, **extra) -> dict:
    # A jump is a move of the raw level, a shift a move of the smoothed one. Each row reports
    # the series its detector measured, so its three level columns always agree with each other.
    level = g["level" if kind == "jump" else "level_smooth"].to_numpy()
    tier_month, anticipation, late = _anticipation(g, onset, t)
    driver_1, driver_2 = _drivers(g, onset, t, direction)
    delta = level[t] - level[onset]
    inflow = float(g["monthly_inflow_eur"].iat[t])
    return {
        "group_id": g["group_id"].iat[t],
        "month": g["month"].iat[t],
        "kind": kind,
        "direction": direction,
        "state_from": g["state"].iat[t - 1],
        "state_to": g["state"].iat[t],
        "onset_month": g["month"].iat[onset],
        "level_at_onset": round(level[onset], 1),
        "level_at_alert": round(level[t], 1),
        "delta_level": round(delta, 1),
        "trend": round(float(g["trend"].iat[t]), 2),
        "compound": round(float(g["compound"].iat[t]), 1),
        "tier": g["tier"].iat[t],
        "driver_1": driver_1,
        "driver_2": driver_2,
        "monthly_inflow_eur": round(inflow, -2),
        # Ranking key only: the size of the move, weighted by where the group sits in the
        # portfolio by inflow. It puts the biggest moves on the biggest books at the top of the
        # feed. Not money: inflow is summed across currencies without conversion, so its
        # absolute value cannot be trusted yet, only its order.
        "severity": round(abs(delta) * float(g["inflow_rank"].iat[t]), 1),
        "tier_change_month": tier_month,
        "anticipation_months": anticipation,
        "late": late,
        **extra,
    }


def _alerts(g: pd.DataFrame) -> list[dict]:
    """Every jump and every state transition worth an alert, for one group, in month order."""
    raw = g["level"].to_numpy()
    changes = np.diff(raw)
    rows, last_jump = [], None
    for t in range(1, len(g)):
        prior = changes[: t - 1]
        if len(prior) < JUMP_MIN_CHANGES:
            continue
        sigma = robust_sigma(prior)
        if abs(changes[t - 1]) < max(JUMP_FLOOR_POINTS, JUMP_SIGMAS * sigma):
            continue
        direction = "down" if changes[t - 1] < 0 else "up"
        # The other half of a spike is not a second event: the first jump's revert message
        # already says the level came back.
        if last_jump and last_jump[1] != direction and t - last_jump[0] <= BUMP_WINDOW_MONTHS:
            continue
        last_jump = (t, direction)
        resolution, resolution_month = _resolution(g, t)
        rows.append(
            _row(
                g,
                t,
                t - 1,
                kind="jump",
                direction=direction,
                sigmas=round(abs(changes[t - 1]) / sigma, 1),
                resolution=resolution,
                resolution_month=resolution_month,
            )
        )
    # An alarm that is already raised is not news again: bending to falling is the same decline
    # crossing a level line. Only entering a direction, or flipping to the other one, alerts.
    alarm = [alarm_direction(state) for state in g["state"]]
    for t in range(1, len(g)):
        if not alarm[t] or alarm[t] == alarm[t - 1]:
            continue
        rows.append(
            _row(
                g,
                t,
                int(g["onset_idx"].iat[t]),
                kind="shift",
                direction=alarm[t],
                sigmas=np.nan,
                resolution="",
                resolution_month=pd.NaT,
            )
        )
    # A jump in the same month as a shift is the same news arriving twice: the shift is the
    # confirmed version of it, so it wins.
    confirmed = {r["month"] for r in rows if r["kind"] == "shift"}
    rows = [r for r in rows if r["kind"] == "shift" or r["month"] not in confirmed]
    return sorted(rows, key=lambda r: (r["month"], r["kind"]))


def detect(scores: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run both detectors over a scored panel.

    Args:
        scores: One row per group-month with ``level``, ``tier``, ``monthly_inflow_eur`` and one
            ``contrib_<pillar>`` column per pillar. Sorted arbitrarily.

    Returns:
        The trajectory table and the alert table, both sorted by group and month.
    """
    scores = scores.sort_values(["group_id", "month"])
    size = scores.groupby("group_id")["monthly_inflow_eur"].median()
    scores["inflow_rank"] = scores["group_id"].map(size.rank(pct=True))

    trajectories, alerts = [], []
    for _, g in scores.groupby("group_id"):
        g = g.reset_index(drop=True).join(states(g["level"].to_numpy()))
        g["compound"] = (g["level_smooth"] + COMPOUND_HORIZON_MONTHS * g["trend"].fillna(0)).clip(
            0, 100
        )
        g["onset_month"] = g["onset_idx"].map(
            lambda i, months=g["month"]: pd.NaT if pd.isna(i) else months.iat[int(i)]
        )
        trajectories.append(g)
        alerts += _alerts(g)

    trajectory = pd.concat(trajectories, ignore_index=True)
    columns = ["group_id", "month", "level_smooth", "trend", "compound", "state", "onset_month"]
    return (
        trajectory[columns].round({"level_smooth": 2, "trend": 2, "compound": 2}),
        pd.DataFrame(alerts, columns=ALERT_COLUMNS).sort_values(
            ["group_id", "month", "kind"], ignore_index=True
        ),
    )


def build(marts_dir: Path = MARTS_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Detect over the published score, sizing each alert with the group's operating inflow."""
    scores = pd.read_parquet(marts_dir / "scores.parquet")
    panel = pd.read_parquet(
        marts_dir / "panel_group.parquet", columns=["group_id", "month", "opin_3m"]
    )
    scores = scores.merge(panel, on=["group_id", "month"], how="left")
    scores["monthly_inflow_eur"] = scores["opin_3m"] / MONTHS_PER_QUARTER
    return detect(scores)


def main() -> None:
    """Build both tables and publish them to the mart."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marts-dir", type=Path, default=MARTS_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    trajectory, alerts = build(args.marts_dir)
    publish("trajectory", trajectory, sources=list(SOURCES), marts_dir=args.marts_dir)
    publish("alerts", alerts, sources=["trajectory"], marts_dir=args.marts_dir)

    resolution = alerts.query("kind == 'jump'")["resolution"].value_counts().to_dict()
    ahead = alerts["anticipation_months"]
    logger.info(
        "%d alerts over %d group-months (%.1f%%) on %d of %d groups: %s",
        len(alerts),
        len(trajectory),
        100 * len(alerts) / len(trajectory),
        alerts["group_id"].nunique(),
        trajectory["group_id"].nunique(),
        alerts.groupby(["kind", "direction"]).size().to_dict(),
    )
    logger.info("jumps resolved %s", resolution)
    logger.info(
        "%.0f%% landed before the tier moved, median %.0f months of anticipation",
        100 * (ahead > 0).mean(),
        ahead[ahead > 0].median(),
    )


if __name__ == "__main__":
    main()

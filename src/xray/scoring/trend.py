"""Trajectory of a level series: smoothing, slope, robust scale and the state machine.

One implementation, shared by `xray.scoring.monitor` and `xray.scoring.mock`, so the demo cannot
drift from the engine.

Every function here is causal: the value at index `t` uses `level[:t+1]` only. That is what lets
the alert table be replayed month by month, because the row dated `t` is exactly what the system
would have raised at the end of `t`.

The series is smoothed before anything is measured on it. The raw level moves a median of 4
points a month (`docs/status.md`, problem 1), which is as large as most of the moves worth
alerting on, so a CUSUM on the raw series would fire on noise alone. Once the level itself is
smoother, `SMOOTHING_ALPHA` moves back towards 1 and the alarms arrive earlier.

Rows must be sorted by month, one row per month, no gaps.
"""

import numpy as np
import pandas as pd

# A trend, and therefore a state, needs this many months of history behind it.
MIN_HISTORY_MONTHS = 6
# Causal EWMA. At 0.4 the median month-on-month move drops from 4.0 points to 2.1, under the
# stability target of 3, at a cost of roughly 1.5 months of lag.
SMOOTHING_ALPHA = 0.4
# Robust scale of the monthly changes, floored so a very quiet group cannot alarm on a fraction
# of a point.
MIN_SIGMA_POINTS = 1.0
CUSUM_REF_MONTHS = 12
CUSUM_SLACK_SIGMAS = 0.75
CUSUM_ALARM_SIGMAS = 4.0
# One outlier month is worth at most this much of the alarm, so a spike alone cannot raise it.
DEVIATION_CLIP_SIGMAS = 2.0
IMPROVING_SLOPE_POINTS = 1.5
BENDING_LEVEL = 60.0
HEALTHY_LEVEL = 70.0
WEAK_LEVEL = 40.0
# Compound score: the level projected this many months along its trend.
COMPOUND_HORIZON_MONTHS = 4

DOWN_STATES = ("bending", "falling")
UP_STATES = ("improving",)


def alarm_direction(state: str) -> str:
    """The alarm a state carries: "down", "up", or "" when it carries none."""
    if state in DOWN_STATES:
        return "down"
    return "up" if state in UP_STATES else ""


def smooth(level: np.ndarray) -> np.ndarray:
    """Causal exponentially weighted mean of a level series."""
    return pd.Series(level).ewm(alpha=SMOOTHING_ALPHA, adjust=False).mean().to_numpy()


def robust_sigma(changes: np.ndarray) -> float:
    """MAD-based scale of a change series, floored at ``MIN_SIGMA_POINTS``."""
    if len(changes) == 0:
        return MIN_SIGMA_POINTS
    mad = float(np.median(np.abs(changes - np.median(changes))))
    return max(1.4826 * mad, MIN_SIGMA_POINTS)


def theil_sen(y: np.ndarray) -> float:
    """Median pairwise slope of ``y``, in points per month."""
    i, j = np.triu_indices(len(y), k=1)
    return float(np.median((y[j] - y[i]) / (j - i)))


def states(level: np.ndarray) -> pd.DataFrame:
    """Smooth a level series and walk the state machine of the research doc over it.

    Args:
        level: One raw level per month, ordered, no gaps.

    Returns:
        One row per input month: ``level_smooth``, ``trend`` (points per month), ``state`` and
        ``onset_idx``, the index of the month the current alarm started building. ``onset_idx``
        is null outside an alarm.
    """
    smoothed = smooth(level)
    rows, s_down, s_up, zero_down, zero_up = [], 0.0, 0.0, 0, 0
    down = up = False
    for t in range(len(smoothed)):
        if t + 1 < MIN_HISTORY_MONTHS:
            rows.append((np.nan, "not_enough_data", None))
            continue
        sigma = robust_sigma(np.diff(smoothed[: t + 1]))
        reference = np.median(smoothed[max(0, t - CUSUM_REF_MONTHS) : t])
        deviation = np.clip(
            (reference - smoothed[t]) / sigma, -DEVIATION_CLIP_SIGMAS, DEVIATION_CLIP_SIGMAS
        )
        s_down = max(0.0, s_down + deviation - CUSUM_SLACK_SIGMAS)
        s_up = max(0.0, s_up - deviation - CUSUM_SLACK_SIGMAS)
        zero_down, zero_up = (t if s_down == 0 else zero_down), (t if s_up == 0 else zero_up)
        slope = theil_sen(smoothed[t - MIN_HISTORY_MONTHS + 1 : t + 1])
        # Latched: once raised, an alarm holds until its CUSUM is back at zero.
        down = s_down > CUSUM_ALARM_SIGMAS or (down and s_down > 0)
        up = s_up > CUSUM_ALARM_SIGMAS or (up and s_up > 0)
        if down:
            state = "falling" if smoothed[t] < BENDING_LEVEL else "bending"
            onset = zero_down + 1
        elif up or slope >= IMPROVING_SLOPE_POINTS:
            state = "improving"
            onset = zero_up + 1 if up else t - MIN_HISTORY_MONTHS + 1
        elif smoothed[t] >= HEALTHY_LEVEL:
            state, onset = "healthy", None
        elif smoothed[t] >= WEAK_LEVEL:
            state, onset = "stable", None
        else:
            state, onset = "weak", None
        rows.append((slope, state, onset))
    out = pd.DataFrame(rows, columns=["trend", "state", "onset_idx"])
    out.insert(0, "level_smooth", smoothed)
    return out

"""Does the score work? The checks from `docs/health-score-research.md` section 7, run as code.

There is no label in the dataset, so every number here is measured against the proxy events in
`xray.scoring.events`. The split is by group, never by row or month, because the hidden test is
whole groups the system has never seen.

Run it after any change to the anchors or the weights, and read the four blocks: discrimination
(does the level rank-order trouble), trajectory (does the trend add anything over the level),
stability (is the level calm enough to alert on) and ablation (does each pillar earn its weight).
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from xray.config import MARTS_DIR
from xray.scoring.anchors import PILLAR_WEIGHTS

logger = logging.getLogger(__name__)

VALIDATION_SPLIT = 0.3
TREND_WINDOW_MONTHS = 6
MIN_TREND_MONTHS = 3
SEED = 2026


def _auc(score: np.ndarray, label: np.ndarray) -> float:
    """Area under the ROC curve, as the rank-sum statistic. Higher score means lower risk here,
    so the result is reported for the inverted score: 0.5 is coin-flip, 1.0 is perfect."""
    if label.sum() == 0 or label.sum() == len(label):
        return float("nan")
    order = pd.Series(-score).rank()
    n_pos, n_neg = label.sum(), (1 - label).sum()
    return float((order[label == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _theil_sen(y: np.ndarray) -> float:
    i, j = np.triu_indices(len(y), k=1)
    return float(np.median((y[j] - y[i]) / (j - i)))


def _split(groups: pd.Series, rng: np.random.Generator) -> set[str]:
    """Hold out whole groups, never rows."""
    unique = np.sort(groups.unique())
    return set(rng.choice(unique, size=int(len(unique) * VALIDATION_SPLIT), replace=False))


def _with_trend(scores: pd.DataFrame) -> pd.DataFrame:
    """Theil-Sen slope of the level over the trailing window, in points per month."""
    out = scores.sort_values(["group_id", "month"]).copy()
    out["trend"] = (
        out.groupby("group_id")["level"]
        .rolling(TREND_WINDOW_MONTHS, min_periods=MIN_TREND_MONTHS)
        .apply(_theil_sen, raw=True)
        .reset_index(level=0, drop=True)
    )
    return out


def report(marts_dir: Path = MARTS_DIR) -> None:
    """Print the four validation blocks for the current score."""
    scores = pd.read_parquet(marts_dir / "scores.parquet")
    events = pd.read_parquet(marts_dir / "events.parquet")
    df = _with_trend(scores).merge(events, on=["group_id", "month"])
    holdout = _split(df["group_id"], np.random.default_rng(SEED))
    val = df[df["group_id"].isin(holdout)]

    print(
        f"\n{len(df)} labelled group-months, {df.group_id.nunique()} groups "
        f"({len(val)} months / {val.group_id.nunique()} groups held out)\n"
    )

    train = df[~df["group_id"].isin(holdout)]
    print("1. DISCRIMINATION: AUC of the level against each event, held-out groups")
    for event in ("cash_negative", "missed_payroll", "inflow_collapse", "distress"):
        a_train = _auc(train["level"].to_numpy(), train[event].to_numpy())
        a_val = _auc(val["level"].to_numpy(), val[event].to_numpy())
        print(
            f"   {event:18s} train {a_train:.3f}   holdout {a_val:.3f}"
            f"   base rate {val[event].mean():.1%}"
        )

    print("\n   Level decile against forward negative cash, held-out groups")
    d = val.assign(decile=pd.qcut(val["level"], 5, labels=False, duplicates="drop"))
    for q, g in d.groupby("decile"):
        print(
            f"   Q{q + 1}  level {g['level'].mean():5.1f}"
            f"   negative cash {g['cash_negative'].mean():5.1%}   n={len(g)}"
        )

    print("\n2. TRAJECTORY: does the trend add signal over the level?")
    t = val.dropna(subset=["trend"])
    print(f"   trend available on {len(t) / len(val):.0%} of held-out months")
    q = t.assign(
        bucket=pd.qcut(
            t["trend"], 4, labels=["falling", "flat-", "flat+", "rising"], duplicates="drop"
        )
    )
    for b, g in q.groupby("bucket", observed=True):
        print(
            f"   {b:8s} trend {g['trend'].mean():+5.2f}/m"
            f"   negative cash {g['cash_negative'].mean():5.1%}   n={len(g)}"
        )
    mid = t[t["level"].between(*t["level"].quantile([0.25, 0.75]))]
    if len(mid) > 20:
        lo, hi = mid[mid.trend < 0], mid[mid.trend > 0]
        print(
            f"   within the middle half of the level: falling {lo.cash_negative.mean():.1%} "
            f"vs rising {hi.cash_negative.mean():.1%}"
        )

    print("\n3. STABILITY")
    step = df.sort_values(["group_id", "month"]).groupby("group_id")["level"].diff().abs()
    print(
        f"   median month-on-month level change {step.median():.2f} points "
        f"(target under 3), p90 {step.quantile(0.9):.2f}"
    )

    print("\n4. ABLATION: AUC against negative cash, dropping one pillar at a time")
    full = _auc(val["level"].to_numpy(), val["cash_negative"].to_numpy())
    print(f"   all pillars            {full:.3f}")
    for pillar in PILLAR_WEIGHTS:
        others = {p: w for p, w in PILLAR_WEIGHTS.items() if p != pillar}
        block = val[list(others)]
        weights = pd.Series(others) * block.notna()
        relevel = 50 + (
            weights.div(weights.sum(axis=1).replace(0, np.nan), axis=0) * (block.fillna(50) - 50)
        ).sum(axis=1)
        delta = _auc(relevel.to_numpy(), val["cash_negative"].to_numpy()) - full
        print(f"   without {pillar:18s} {full + delta:.3f}  ({delta:+.3f})")
    print()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    report()


if __name__ == "__main__":
    main()

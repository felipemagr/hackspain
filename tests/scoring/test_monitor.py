import numpy as np
import pandas as pd
import pytest

from xray.scoring.anchors import PILLAR_WEIGHTS, TIER_BOUNDS
from xray.scoring.monitor import detect

PILLARS = list(PILLAR_WEIGHTS)


def _scores(levels: list[float], driver: str = "liquidity", group_id: str = "g1") -> pd.DataFrame:
    """One group whose level follows ``levels``, with the whole move charged to one pillar."""
    level = pd.Series(levels, dtype=float)
    out = pd.DataFrame(
        {
            "group_id": group_id,
            "month": pd.date_range("2025-01-01", periods=len(level), freq="MS"),
            "level": level,
            "tier": [next(t for bound, t in TIER_BOUNDS if v >= bound) for v in level],
            "monthly_inflow_eur": 300_000.0,
        }
    )
    for pillar in PILLARS:
        out[f"contrib_{pillar}"] = level - 50 if pillar == driver else 0.0
    return out


def _flat(n: int = 10, at: float = 80.0) -> list[float]:
    """A quiet series with just enough wobble to have a scale of its own."""
    return list(at + np.resize([0.0, 0.6, -0.6, 0.3], n))


class TestJumps:
    def test_spike_that_comes_back_is_a_bump(self):
        levels = _flat(8) + [55.0] + _flat(4)
        _, alerts = detect(_scores(levels))
        jumps = alerts[alerts["kind"] == "jump"]

        # One alert, not two: the recovery is the same spike and its revert message covers it.
        assert len(jumps) == 1
        assert jumps["direction"].iat[0] == "down"
        assert jumps["resolution"].iat[0] == "reverted"
        # Two months after the spike, which is when the revert became knowable.
        assert jumps["resolution_month"].iat[0] == pd.Timestamp("2025-11-01")

    def test_spike_that_holds_is_sustained(self):
        _, alerts = detect(_scores(_flat(8) + _flat(5, at=55.0)))
        jumps = alerts[alerts["kind"] == "jump"]

        assert jumps["resolution"].tolist() == ["sustained"]

    def test_jump_names_the_pillar_that_moved(self):
        _, alerts = detect(_scores(_flat(8) + [55.0] + _flat(4), driver="collections"))

        assert alerts["driver_1"].iat[0] == "collections"

    def test_quiet_series_raises_nothing(self):
        _, alerts = detect(_scores(_flat(20)))

        assert alerts.empty

    def test_a_move_inside_the_group_own_noise_is_not_a_jump(self):
        # Ten points is the floor, but this group swings twenty every month.
        noisy = list(80 + np.resize([0.0, 20.0, -20.0, 10.0], 16)) + [70.0]
        _, alerts = detect(_scores(noisy))

        assert (alerts["kind"] == "jump").sum() == 0


class TestShifts:
    def test_sustained_decline_raises_one_alert_with_its_onset(self):
        _, alerts = detect(_scores(_flat(6) + list(np.arange(79, 55, -2.0))))
        shifts = alerts[alerts["kind"] == "shift"]

        assert len(shifts) == 1
        assert shifts["direction"].iat[0] == "down"
        assert shifts["state_to"].iat[0] in ("bending", "falling")
        assert shifts["onset_month"].iat[0] < shifts["month"].iat[0]
        assert shifts["trend"].iat[0] < 0

    def test_improvement_is_reported_as_well_as_decline(self):
        _, alerts = detect(_scores(_flat(6, at=45.0) + list(np.arange(46, 70, 2.0))))
        shifts = alerts[alerts["kind"] == "shift"]

        assert shifts["direction"].tolist() == ["up"]
        assert shifts["state_to"].iat[0] == "improving"

    def test_an_alarm_already_raised_is_not_news_again(self):
        # A long slide crosses the bending/falling line, which is not a second event.
        _, alerts = detect(_scores(_flat(6) + list(np.arange(79, 25, -3.0))))
        shifts = alerts[alerts["kind"] == "shift"]

        assert len(shifts) == 1


class TestCausality:
    """The replay claim: a row dated `t` must not depend on anything after `t`."""

    def test_truncating_the_future_leaves_past_alerts_unchanged(self):
        levels = _flat(6) + list(np.arange(79, 45, -2.0)) + _flat(4, at=45.0)
        scores = _scores(levels)
        cutoff = scores["month"].iat[14]

        _, full = detect(scores)
        _, truncated = detect(scores[scores["month"] <= cutoff])

        # Hindsight columns are excluded: they are measurements, never sent in a message.
        live = [c for c in full.columns if c not in ("tier_change_month", "anticipation_months")]
        pd.testing.assert_frame_equal(
            truncated[live],
            full[full["month"] <= cutoff][live].reset_index(drop=True),
            check_dtype=False,
        )


class TestSeverity:
    def test_the_bigger_book_ranks_first_on_an_equal_move(self):
        small = _scores(_flat(8) + [55.0] + _flat(4), group_id="small")
        big = small.assign(group_id="big", monthly_inflow_eur=9_000_000.0)

        _, alerts = detect(pd.concat([small, big], ignore_index=True))
        jumps = alerts[alerts["kind"] == "jump"].set_index("group_id")

        assert jumps.loc["big", "delta_level"] == jumps.loc["small", "delta_level"]
        assert jumps.loc["big", "severity"] > jumps.loc["small", "severity"]
        assert alerts.nlargest(1, "severity")["group_id"].iat[0] == "big"


class TestTrajectory:
    def test_every_month_gets_a_state_and_a_compound_score(self):
        trajectory, _ = detect(_scores(_flat(12)))

        assert len(trajectory) == 12
        assert trajectory["state"].iloc[:5].eq("not_enough_data").all()
        assert trajectory["compound"].between(0, 100).all()
        assert trajectory["level_smooth"].iat[-1] == pytest.approx(80, abs=1)

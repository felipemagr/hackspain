import numpy as np
import pandas as pd
import pytest

from xray.scoring.anchors import ANCHORS, CAP_LEVEL, PILLAR_WEIGHTS
from xray.scoring.score import indicators, level, pillars, sub_scores

MONTHS = pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"])


def _panel(**overrides):
    """Three months of one group, healthy defaults, overridden per column."""
    base = {
        "group_id": "g1",
        "month": MONTHS,
        "cash": 90_000.0,
        "opin_3m": 300_000.0,
        "opout_3m": 273_000.0,
        "opin_12m": 1_200_000.0,
        "opout_12m": 1_100_000.0,
        "debt_service_12m": 60_000.0,
        "ap_overdue_ratio": 0.1,
        "ap_days_late": 2.0,
        "ar_overdue_ratio": 0.1,
        "ar_days_late": 3.0,
    }
    return pd.DataFrame({**base, **overrides})


class TestIndicators:
    def test_buffer_days_is_cash_over_daily_operating_outflow(self):
        # 273k over 91 days is 3k a day, and a 3-month mean of a flat 90k is 90k: 30 days.
        out = indicators(_panel())
        assert out["buffer_days"].iloc[-1] == pytest.approx(30.0, abs=0.1)

    def test_buffer_days_smooths_a_one_month_cash_spike(self):
        spiked = indicators(_panel(cash=[90_000.0, 90_000.0, 270_000.0]))
        assert spiked["buffer_days"].iloc[-1] == pytest.approx(50.0, abs=0.1)

    def test_negative_cash_share_counts_the_trailing_window(self):
        out = indicators(_panel(cash=[-1_000.0, 90_000.0, 90_000.0]))
        assert out["negative_cash_share"].tolist() == [1.0, 0.5, pytest.approx(1 / 3)]

    def test_indicator_is_nan_when_its_basis_is_missing(self):
        out = indicators(_panel(opin_12m=0.0, ap_overdue_ratio=np.nan))
        assert out["debt_burden"].isna().all()
        assert out["ap_overdue_ratio"].isna().all()


class TestSubScores:
    def test_anchor_breakpoint_maps_to_its_score(self):
        out = sub_scores(_subs(**{n: c[1][0] for n, (_, _, c) in ANCHORS.items()}))
        for name, (_, _, curve) in ANCHORS.items():
            assert out[name].iloc[0] == pytest.approx(curve[1][1])

    def test_value_beyond_the_last_anchor_is_clamped(self):
        out = sub_scores(_subs(buffer_days=10_000.0, ap_days_late=-5.0))
        assert out["buffer_days"].iloc[0] == 100
        assert out["ap_days_late"].iloc[0] == 100


def _subs(**overrides):
    """A full frame of 0-100 sub-scores, one column per anchored indicator."""
    base = {"group_id": "g1", "month": MONTHS, **dict.fromkeys(ANCHORS, 50.0)}
    return pd.DataFrame({**base, **overrides})


class TestPillars:
    def test_pillar_is_the_weighted_mean_of_its_indicators(self):
        # payment discipline weights its two indicators 0.60 and 0.40.
        subs = _subs(ap_overdue_ratio=80.0, ap_days_late=30.0)
        assert pillars(subs)["payment_discipline"].iloc[0] == pytest.approx(60.0)

    def test_pillar_renormalises_over_the_indicators_present(self):
        subs = _subs(ap_overdue_ratio=np.nan, ap_days_late=30.0)
        assert pillars(subs)["payment_discipline"].iloc[0] == pytest.approx(30.0)

    def test_pillar_is_nan_when_no_indicator_is_present(self):
        subs = _subs(ap_overdue_ratio=np.nan, ap_days_late=np.nan)
        assert pillars(subs)["payment_discipline"].isna().all()


class TestLevel:
    def test_contributions_sum_back_to_the_level(self):
        out = level(_subs(**dict.fromkeys(PILLAR_WEIGHTS, 70.0)))
        contrib = out[[f"contrib_{p}" for p in PILLAR_WEIGHTS]].sum(axis=1)
        assert (50 + contrib).round(6).equals(out["level_uncapped"].round(6))

    def test_weights_renormalise_when_a_group_has_no_invoices(self):
        pil = _subs(**dict.fromkeys(PILLAR_WEIGHTS, 70.0))
        pil[["payment_discipline", "collections"]] = np.nan
        out = level(pil)
        # The surviving pillars all sit at 70, so the renormalised level is 70, not diluted to 50.
        assert out["level"].iloc[0] == pytest.approx(70.0)
        assert out["coverage"].iloc[0] == pytest.approx(0.60)

    def test_failing_liquidity_caps_an_otherwise_high_level(self):
        pil = _subs(**{**dict.fromkeys(PILLAR_WEIGHTS, 95.0), "liquidity": 10.0})
        out = level(pil)
        assert out["is_capped"].all()
        assert out["level"].iloc[0] == CAP_LEVEL
        assert out["level_uncapped"].iloc[0] > CAP_LEVEL

    def test_tier_follows_the_level(self):
        pil = _subs(**dict.fromkeys(PILLAR_WEIGHTS, [80.0, 55.0, 20.0]))
        assert level(pil)["tier"].tolist() == ["healthy", "coping", "vulnerable"]

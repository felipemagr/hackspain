import numpy as np
import pandas as pd
import pytest

from xray.scoring.anchors import ANCHORS, CAP_LEVEL, PILLAR_WEIGHTS
from xray.scoring.score import indicators, level, pillars, score, sub_scores

MONTHS = pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"])


def _panel(**overrides):
    """Three months of one group, healthy defaults, overridden per column."""
    base = {
        "group_id": "g1",
        "month": MONTHS,
        "is_covered": True,
        "has_erp": True,
        "months_observed": [1.0, 2.0, 3.0],
        "n_companies": 1,
        "cash": 90_000.0,
        "inflow_op": 100_000.0,
        "outflow_op": 91_250.0,
        "opin_12m": 1_200_000.0,
        "debt_service_12m": 60_000.0,
        "ap_paid": 50_000.0,
        "ap_late_days": 100_000.0,
        "ap_overdue_90d": 10_000.0,
        "ar_collected": 60_000.0,
        "ar_late_days": 180_000.0,
        "ar_overdue_90d": 20_000.0,
    }
    return pd.DataFrame({**base, **overrides})


class TestIndicators:
    def test_buffer_days_is_cash_over_daily_operating_outflow(self):
        # 91,250 a month is 3,000 a day, and a flat 90k of cash is 30 days of it.
        out = indicators(_panel())
        assert out["buffer_days"].iloc[-1] == pytest.approx(30.0, abs=0.1)

    def test_buffer_days_smooths_a_one_month_cash_spike(self):
        spiked = indicators(_panel(cash=[90_000.0, 90_000.0, 270_000.0]))
        assert spiked["buffer_days"].iloc[-1] == pytest.approx(50.0, abs=0.1)

    def test_negative_cash_share_counts_the_trailing_window(self):
        out = indicators(_panel(cash=[-1_000.0, 90_000.0, 90_000.0]))
        assert out["negative_cash_share"].tolist() == [1.0, 0.5, pytest.approx(1 / 3)]

    def test_an_emptied_account_is_not_overdrawn(self):
        # Reconstruction leaves a zero balance at +-1e-10 depending on summation order.
        out = indicators(_panel(cash=[-1e-10, 1e-10, -0.5]))
        assert out["negative_cash_share"].eq(0).all()

    def test_lateness_is_a_ratio_of_window_sums(self):
        # 100k late-days on 50k paid is 2 days a month; the window keeps it at 2, not an average
        # of per-month ratios that a zero-paid month would distort.
        out = indicators(
            _panel(ap_paid=[50_000.0, 0.0, 50_000.0], ap_late_days=[100_000.0, 0.0, 100_000.0])
        )
        assert out["ap_days_late"].iloc[-1] == pytest.approx(2.0)

    def test_overdue_months_is_overdue_over_monthly_paid_flow(self):
        out = indicators(_panel())
        # 10k overdue against 50k paid a month is 0.2 months of payables.
        assert out["ap_overdue_months"].iloc[-1] == pytest.approx(0.2)

    def test_margin_needs_three_months(self):
        out = indicators(_panel())
        assert out["op_margin"].iloc[:2].isna().all()
        assert out["op_margin"].iloc[-1] == pytest.approx(0.0875)

    def test_invoice_indicators_are_absent_without_erp(self):
        out = indicators(_panel(has_erp=False))
        assert out[["ap_days_late", "ap_overdue_months", "ar_days_late"]].isna().all().all()

    def test_indicator_is_nan_when_its_basis_is_missing(self):
        out = indicators(_panel(opin_12m=0.0))
        assert out["debt_service_ratio"].isna().all()


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
        subs = _subs(ap_overdue_months=80.0, ap_days_late=30.0)
        assert pillars(subs)["payment_discipline"].iloc[0] == pytest.approx(55.0)

    def test_pillar_renormalises_over_the_indicators_present(self):
        subs = _subs(ap_overdue_months=np.nan, ap_days_late=30.0)
        assert pillars(subs)["payment_discipline"].iloc[0] == pytest.approx(30.0)

    def test_pillar_is_nan_when_no_indicator_is_present(self):
        subs = _subs(ap_overdue_months=np.nan, ap_days_late=np.nan)
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
        assert out["coverage"].iloc[0] == pytest.approx(0.70)

    def test_failing_liquidity_caps_an_otherwise_high_level(self):
        pil = _subs(**{**dict.fromkeys(PILLAR_WEIGHTS, 95.0), "liquidity": 10.0})
        out = level(pil)
        assert out["is_capped"].all()
        assert out["level"].iloc[0] == CAP_LEVEL
        assert out["level_uncapped"].iloc[0] > CAP_LEVEL

    def test_tier_follows_the_level(self):
        pil = _subs(**dict.fromkeys(PILLAR_WEIGHTS, [80.0, 55.0, 20.0]))
        assert level(pil)["tier"].tolist() == ["healthy", "coping", "vulnerable"]


class TestScore:
    def test_one_row_per_covered_month_within_range(self):
        out = score(_panel(is_covered=[True, False, True]))
        assert len(out) == 2
        assert out["level"].between(0, 100).all()

    def test_scores_a_company_panel_by_company_id(self):
        panel = _panel().rename(columns={"group_id": "company_id"}).assign(group_id="g1")
        out = score(panel, key="company_id")
        assert out["company_id"].eq("g1").all()
        assert "group_id" in out

    def test_pillar_columns_carry_the_pillar_score_not_the_raw_indicator(self):
        out = score(_panel())
        assert out["debt_burden"].iloc[-1] == pytest.approx(65.0)
        assert out["debt_service_ratio"].iloc[-1] == pytest.approx(0.05)

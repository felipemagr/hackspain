import numpy as np
import pandas as pd

from xray.scoring.score import build


def _panel() -> pd.DataFrame:
    months = pd.date_range("2024-09-01", periods=8, freq="MS")
    return pd.DataFrame(
        {
            "group_id": "g1",
            "month": months,
            "is_covered": True,
            "months_observed": np.arange(1, 9),
            "n_currencies": 1,
            "has_cash": True,
            "cash_is_extrapolated": False,
            "cash": 1000.0,
            "has_erp": True,
            "inflow": 160.0,
            "outflow": 100.0,
            "operating_inflow": 100.0,
            "operating_outflow": 60.0,
            "uncategorized_amount": 60.0,
            "ap_open": 100.0,
            "ap_overdue": 10.0,
            "ar_open": 100.0,
            "ar_overdue": 0.0,
            "ap_paid": 100.0,
            "ar_collected": 100.0,
            "ap_late_days": 0.0,
            "ar_late_days": 0.0,
            "debt_repayment_outflow": 5.0,
            "interest_outflow": 1.0,
        }
    )


def test_score_is_bounded_and_drivers_rebuild_it():
    tables = build(_panel())
    scores = tables["scores"].dropna(subset=["level"])
    drivers = tables["drivers"]
    contributions = drivers.groupby(["group_id", "month"])["contribution"].sum()

    assert len(scores) == 6
    assert scores["level"].between(0, 100).all()
    np.testing.assert_allclose(
        scores["level_uncapped"],
        50 + contributions.loc[pd.MultiIndex.from_frame(scores[["group_id", "month"]])],
    )


def test_unknown_movements_change_coverage_not_the_score():
    original = build(_panel())["scores"]
    changed = _panel()
    changed["uncategorized_amount"] = 600.0
    changed["inflow"] = 700.0
    alternative = build(changed)["scores"]

    pd.testing.assert_series_equal(original["level"], alternative["level"])
    assert alternative["uncategorized_share"].iat[-1] > original["uncategorized_share"].iat[-1]


def test_future_month_does_not_change_past_score():
    panel = _panel()
    full = build(panel)["scores"].iloc[5]
    truncated = build(panel.iloc[:6])["scores"].iloc[5]

    pd.testing.assert_series_equal(full, truncated)


def test_invoice_pillars_are_absent_without_erp():
    panel = _panel()
    panel["has_erp"] = False
    scores = build(panel)["scores"]

    assert scores[["payment_discipline", "collections"]].isna().all().all()
    assert scores["coverage"].iat[-1] == 0.65


def test_mixed_currency_is_explicitly_flagged():
    panel = _panel()
    panel["n_currencies"] = 2

    assert build(panel)["scores"]["currency_mixed"].all()

import pandas as pd
import pytest

from xray.scoring.serve import _companies, _with_panel

MONTHS = pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"])


def _company_panel(company_id: str, months: pd.DatetimeIndex) -> pd.DataFrame:
    """One company of group g1, healthy defaults, covered on the given months."""
    return pd.DataFrame(
        {
            "company_id": company_id,
            "group_id": "g1",
            "month": months,
            "is_covered": True,
            "has_erp": False,
            "months_observed": [float(i) for i in range(1, len(months) + 1)],
            "n_companies": 1,
            "cash": 90_000.0,
            "inflow_op": 100_000.0,
            "outflow_op": 91_250.0,
            "opin_3m": 300_000.0,
            "opin_12m": 1_200_000.0,
            "debt_service_12m": 60_000.0,
            "ap_paid": 0.0,
            "ap_late_days": 0.0,
            "ap_overdue_90d": 0.0,
            "ar_collected": 0.0,
            "ar_late_days": 0.0,
            "ar_overdue_90d": 0.0,
        }
    )


class TestCompanies:
    def test_carries_each_company_own_months_observed(self):
        # c2 joined in the group's last month: its level rests on one month, the group's on three.
        panel = pd.concat([_company_panel("c1", MONTHS), _company_panel("c2", MONTHS[-1:])])
        scores = pd.DataFrame({"group_id": "g1", "month": MONTHS})
        company_scores = panel[["company_id", "month"]].assign(level=50.0)
        out = _companies(panel, scores, company_scores, pd.DataFrame()).set_index("company_id")
        assert out.loc["c1", "months_observed"] == 3
        assert out.loc["c2", "months_observed"] == 1


def test_treasury_volatility_uses_only_observed_months():
    months = pd.date_range("2025-01-01", periods=4, freq="MS")
    panel = pd.DataFrame(
        {
            "group_id": "g1",
            "month": months,
            "is_covered": True,
            "cash": [100_000.0] * 4,
            "cash_is_extrapolated": False,
            "opin_3m": [30_000.0] * 4,
            "opout_3m": [24_000.0] * 4,
            "opin_12m": [120_000.0] * 4,
            "opout_12m": [96_000.0] * 4,
            "debt_service_12m": [12_000.0] * 4,
            "inflow_op": [10_000.0, 11_000.0, 12_000.0, 1_000_000.0],
            "outflow_op": [8_000.0] * 4,
            "debt_repayment_outflow": [1_000.0] * 4,
            "interest_outflow": [0.0] * 4,
        }
    )
    scores = panel[["group_id", "month"]]
    out = _with_panel(scores, panel)

    assert pd.isna(out.loc[1, "net_flow_volatility_eur"])
    assert out.loc[2, "net_flow_volatility_eur"] == pytest.approx(1_000.0)
    assert out.loc[2, "cash_eur"] == 100_000.0
    assert out.loc[2, "monthly_outflow_eur"] == 8_000.0

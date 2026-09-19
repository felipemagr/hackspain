import pandas as pd

from xray.scoring.serve import _companies

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

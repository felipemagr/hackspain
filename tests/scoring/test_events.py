import pandas as pd

from xray.scoring.events import HORIZON_MONTHS, build

MONTHS = pd.date_range("2025-01-01", periods=12, freq="MS")


def _panel(tmp_path, **overrides):
    """Twelve months of one group with no trouble in them, overridden per column."""
    base = {
        "group_id": "g1",
        "month": MONTHS,
        "is_covered": True,
        "has_cash": True,
        "cash": 10_000.0,
        "salary_outflow": 5_000.0,
        "opin_3m": 100_000.0,
    }
    marts = tmp_path / "marts"
    marts.mkdir(exist_ok=True)
    pd.DataFrame({**base, **overrides}).to_parquet(marts / "panel_group.parquet", index=False)
    return marts


class TestHorizon:
    def test_last_months_carry_no_label(self, tmp_path):
        out = build(_panel(tmp_path))
        assert len(out) == len(MONTHS) - HORIZON_MONTHS
        assert out["month"].max() == MONTHS[-1] - pd.DateOffset(months=HORIZON_MONTHS)

    def test_event_is_flagged_only_on_the_months_that_precede_it(self, tmp_path):
        cash = [10_000.0] * 12
        cash[8] = -500.0
        out = build(_panel(tmp_path, cash=cash)).set_index("month")["cash_negative"]
        # Month 8 is inside the 6-month horizon of months 2 through 5, not of months 0 and 1.
        assert out.loc[MONTHS[2:6]].eq(1).all()
        assert out.loc[MONTHS[0:2]].eq(0).all()


class TestEvents:
    def test_missed_payroll_needs_a_payroll_history_first(self, tmp_path):
        salary = [0.0, 0.0, 5_000.0, 5_000.0, 5_000.0, 0.0] + [5_000.0] * 6
        out = build(_panel(tmp_path, salary_outflow=salary))
        # The gap at month 5 follows three paydays, so it counts; the gaps at 0 and 1 do not.
        assert out["missed_payroll"].iloc[0] == 1
        assert build(_panel(tmp_path, salary_outflow=[0.0] * 12))["missed_payroll"].eq(0).all()

    def test_inflow_collapse_needs_a_halving(self, tmp_path):
        mild = [100_000.0] * 6 + [80_000.0] * 6
        assert build(_panel(tmp_path, opin_3m=mild))["inflow_collapse"].eq(0).all()
        steep = [100_000.0] * 6 + [40_000.0] * 6
        assert build(_panel(tmp_path, opin_3m=steep))["inflow_collapse"].iloc[0] == 1

    def test_distress_excludes_revenue_collapse(self, tmp_path):
        steep = [100_000.0] * 6 + [40_000.0] * 6
        out = build(_panel(tmp_path, opin_3m=steep))
        assert out["inflow_collapse"].iloc[0] == 1
        assert out["distress"].iloc[0] == 0

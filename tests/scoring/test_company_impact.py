import pandas as pd

from xray.pipeline.panel import _ADDITIVE
from xray.scoring.company_impact import impacts


def _panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for company_id, cash, inflow in [("c1", 500_000.0, 150_000.0), ("c2", -50_000.0, 10_000.0)]:
        row = dict.fromkeys(_ADDITIVE, 0.0)
        row.update(
            company_id=company_id,
            group_id="g1",
            month=pd.Timestamp("2026-01-01"),
            cash=cash,
            inflow_op=inflow,
            outflow_op=100_000.0,
            has_erp=False,
            is_covered=True,
            has_cash=True,
            cash_is_extrapolated=False,
        )
        rows.append(row)
    company = pd.DataFrame(rows)
    group = company[list(_ADDITIVE)].sum().to_frame().T
    group["group_id"] = "g1"
    group["month"] = pd.Timestamp("2026-01-01")
    group["n_companies"] = 2
    group["n_currencies"] = 1
    return group, company


def test_company_pressure_distinguishes_healthy_and_weak_subsidiary():
    group, company = _panels()
    scores = pd.DataFrame(
        {
            "group_id": ["g1"],
            "month": [pd.Timestamp("2026-01-01")],
            "level": [55.0],
            "coverage": [0.7],
        }
    )

    result = impacts(group, company, scores).set_index("company_id")

    assert result.loc["c2", "impact_points"] > 0
    assert result.loc["c1", "impact_points"] < 0


def test_company_pressure_requires_comparable_pillars():
    group, company = _panels()
    scores = pd.DataFrame(
        {
            "group_id": ["g1"],
            "month": [pd.Timestamp("2026-01-01")],
            "level": [55.0],
            "coverage": [1.0],
        }
    )

    result = impacts(group, company, scores)

    assert result["impact_points"].isna().all()

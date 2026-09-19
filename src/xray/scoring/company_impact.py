"""Recompute each group without one subsidiary to measure its score pressure."""

import duckdb
import numpy as np
import pandas as pd

from xray.pipeline.panel import _ADDITIVE, _finalize_sql
from xray.scoring.score import score


def impacts(
    panel_group: pd.DataFrame, panel_company: pd.DataFrame, group_scores: pd.DataFrame
) -> pd.DataFrame:
    """Return positive points when removing a company improves its group's level."""
    columns = ["company_id", "group_id", "month", "impact_points"]
    if panel_group.empty or panel_company.empty:
        return pd.DataFrame(columns=columns)

    additive = ", ".join(
        f"coalesce(g.{col}, 0) - coalesce(c.{col}, 0) as {col}" for col in _ADDITIVE
    )
    source = f"""
        select c.company_id, c.group_id, c.month,
            g.n_companies - 1 as n_companies,
            g.n_currencies,
            (sum(c.has_erp::int) over (partition by c.group_id, c.month)
                - c.has_erp::int) > 0 as has_erp,
            (sum(c.is_covered::int) over (partition by c.group_id, c.month)
                - c.is_covered::int) > 0 as is_covered,
            (sum((not c.has_cash)::int) over (partition by c.group_id, c.month)
                - (not c.has_cash)::int) = 0 as has_cash,
            (sum(c.cash_is_extrapolated::int) over (partition by c.group_id, c.month)
                - c.cash_is_extrapolated::int) > 0 as cash_is_extrapolated,
            {additive}
        from company c
        join groups g using (group_id, month)
        where g.n_companies > 1
    """
    with duckdb.connect() as con:
        con.register("company", panel_company)
        con.register("groups", panel_group)
        remaining = con.sql(_finalize_sql(source, "company_id")).df()
    if remaining.empty:
        return pd.DataFrame(columns=columns)

    without = score(remaining, key="company_id")
    original = group_scores[["group_id", "month", "level", "coverage"]].rename(
        columns={"level": "group_level", "coverage": "group_coverage"}
    )
    compared = without.merge(original, on=["group_id", "month"])
    comparable = np.isclose(compared["coverage"], compared["group_coverage"])
    compared["impact_points"] = np.where(
        comparable, compared["level"] - compared["group_level"], np.nan
    )
    return compared[columns]

"""Proxy distress events: the closest thing to a label this dataset has.

No file in the challenge carries an outcome, so the score cannot be trained. What the data does
carry is the future: for a month `t`, whether the group ran into trouble over `t+1..t+HORIZON`.
That is manufactured here, from the panel alone, and used to calibrate anchors, check that each
indicator points the right way and measure anticipation.

These columns are the ruler, never a feature. A row's flags describe months strictly after `t`,
so feeding one back into the score at `t` would leak the answer. The last HORIZON_MONTHS of every
group therefore carry no label: they are dropped rather than filled with false.
"""

import logging
from pathlib import Path

import duckdb
import pandas as pd

from xray.config import MARTS_DIR
from xray.pipeline.lineage import publish

logger = logging.getLogger(__name__)

SOURCES = ("panel_group",)

HORIZON_MONTHS = 6
# A payroll history this long before a gap counts as a missed payment rather than a company that
# simply has no employees on the books.
PAYROLL_HISTORY_MONTHS = 3
# Operating inflow this far below its level at `t`, over a 3-month window, is a revenue collapse.
# At 0.7 it fires on 36% of months, which is ordinary variation rather than collapse.
INFLOW_COLLAPSE_RATIO = 0.5


def _sql(panel_path: Path) -> str:
    return f"""
    with p as (
        select group_id, month, cash, has_cash, salary_outflow, opin_3m,
            sum(case when salary_outflow > 0 then 1 else 0 end) over (
                partition by group_id order by month
                rows between unbounded preceding and 1 preceding
            ) as prior_paydays,
            max(month) over (partition by group_id) as last_month
        from read_parquet('{panel_path}') where is_covered
    ),
    fwd as (
        select
            a.group_id, a.month,
            max(case when b.has_cash and b.cash < 0 then 1 else 0 end) as cash_negative,
            max(case when b.salary_outflow = 0 and b.prior_paydays >= {PAYROLL_HISTORY_MONTHS}
                     then 1 else 0 end) as missed_payroll,
            max(case when a.opin_3m > 0 and b.opin_3m < {INFLOW_COLLAPSE_RATIO} * a.opin_3m
                     then 1 else 0 end) as inflow_collapse
        from p a join p b
          on b.group_id = a.group_id
         and b.month > a.month
         and b.month <= a.month + interval {HORIZON_MONTHS} month
        -- Only months with the full horizon ahead of them can carry a label.
        where a.month <= a.last_month - interval {HORIZON_MONTHS} month
        group by 1, 2
    )
    -- `distress` is the two hard liquidity events only. A revenue collapse is a different
    -- thing, reported beside them rather than folded in: it is four times as common and
    -- would drown the signal the anchors are calibrated against.
    select *, greatest(cash_negative, missed_payroll) as distress
    from fwd order by group_id, month
    """


def build(marts_dir: Path = MARTS_DIR) -> pd.DataFrame:
    """Label every group-month that has a full forward horizon behind it.

    Args:
        marts_dir: Directory holding ``panel_group.parquet``.

    Returns:
        One row per labelled group-month with a flag per event and a combined ``distress``.
    """
    return duckdb.sql(_sql(marts_dir / "panel_group.parquet")).df()


def main() -> None:
    """Build the event table and publish it to the mart."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    events = build()
    publish("events", events, sources=list(SOURCES))
    rates = {
        c: f"{events[c].mean():.1%}"
        for c in ("cash_negative", "missed_payroll", "inflow_collapse", "distress")
    }
    logger.info("%s labelled group-months, rates %s", len(events), rates)


if __name__ == "__main__":
    main()

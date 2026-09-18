"""Reconstruct a monthly cash balance per company by rolling the final snapshot backwards.

`balances.csv` is a single snapshot at 2026-09-01, so on its own it is month-24 information and
cannot feed an earlier month. Transactions are dated, so the snapshot can be walked back:

    cash(product, t) = balance(2026-09-01) - (flows after t)

Only checking and saving accounts count. Cards are a liability and TPV accounts sweep to zero, so
including either would misstate what the company can actually spend.

Two limits on the result, both recorded rather than hidden:

- Before a company's first transaction there is nothing to roll back, so the series is flat at the
  implied opening balance. Those months carry `cash_is_extrapolated`.
- The roll-back uses cleaned transactions, which drop pending rows, zero amounts and the
  2026-09-01 day itself, so the level carries a small error against the true balance. Ranking
  companies within a month is unaffected, and that is what the score uses.

This is not a leak, though it reads like one. `cash(t)` is the balance that stood at month `t`;
later transactions are used to recover that fact, not to describe it with hindsight. Compare
`invoices.status`, which is genuinely a leak because it puts July's value on a March row. The
consequence is that the truncation test in `tests/test_panel.py` does not constrain this column:
it is checked by `tests/test_cash.py` against a hand-built series instead.
"""

import logging
from pathlib import Path

import duckdb
import pandas as pd

from xray.config import (
    CASH_ACCOUNT_TYPES,
    MARTS_DIR,
    PROCESSED_DATA_DIR,
    WINDOW_FIRST_MONTH,
    WINDOW_LAST_MONTH,
)
from xray.lineage import publish

logger = logging.getLogger(__name__)

SOURCES = ("balances", "banking_products", "transactions")


def build(processed_dir: Path = PROCESSED_DATA_DIR) -> pd.DataFrame:
    """Reconstruct monthly closing cash per company.

    Args:
        processed_dir: Directory holding the output of ``xray.clean``.

    Returns:
        One row per company per month: `cash`, `n_cash_accounts`, `cash_is_extrapolated`.
    """
    types = ", ".join(f"'{t}'" for t in CASH_ACCOUNT_TYPES)
    sql = f"""
    with accounts as (
        select product_id from read_parquet('{processed_dir / "banking_products.parquet"}')
        where type in ({types})
    ),
    final as (
        select b.product_id, b.company_id, b.balance
        from read_parquet('{processed_dir / "balances.parquet"}') b
        join accounts using (product_id)
    ),
    months as (
        select unnest(generate_series(
            date '{WINDOW_FIRST_MONTH}', date '{WINDOW_LAST_MONTH}', interval 1 month
        ))::date as month
    ),
    flow as (
        select t.product_id, t.month::date as month, sum(t.amount) as flow
        from read_parquet('{processed_dir / "transactions.parquet"}') t
        join accounts using (product_id)
        group by 1, 2
    ),
    total as (select product_id, sum(flow) as total_flow from flow group by 1),
    -- Roll forward from the implied opening balance rather than backward from the snapshot:
    -- the two are the same arithmetic and this one is a plain window, not a correlated subquery.
    rolled as (
        select
            f.company_id,
            m.month,
            f.balance
              - coalesce(t.total_flow, 0)
              + sum(coalesce(fl.flow, 0)) over (
                    partition by f.product_id order by m.month rows unbounded preceding
                ) as cash
        from final f
        cross join months m
        left join flow fl on fl.product_id = f.product_id and fl.month = m.month
        left join total t on t.product_id = f.product_id
    ),
    -- Visibility into the cash series starts with the first movement on a cash account, not
    -- with the company's first transaction anywhere: a card-only month tells us nothing here.
    first_activity as (
        select t.company_id, min(t.month)::date as first_month
        from read_parquet('{processed_dir / "transactions.parquet"}') t
        join accounts using (product_id)
        group by 1
    )
    select
        r.company_id,
        r.month,
        sum(r.cash) as cash,
        count(*) as n_cash_accounts,
        coalesce(r.month < a.first_month, true) as cash_is_extrapolated
    from rolled r
    left join first_activity a on a.company_id = r.company_id
    group by 1, 2, 5
    order by 1, 2
    """
    con = duckdb.connect()
    try:
        return con.sql(sql).df()
    finally:
        con.close()


def main() -> None:
    """Build the cash table and publish it to the mart."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    publish("cash_monthly", build(), sources=list(SOURCES), marts_dir=MARTS_DIR)


if __name__ == "__main__":
    main()

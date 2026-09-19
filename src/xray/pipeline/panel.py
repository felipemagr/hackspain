"""Build the monthly panel: one row per entity per month, nothing from the future.

The panel is the contract between the pipeline and everything downstream. Every column is
computed from data at or before that month's last day, so a row can be read as "what the system
knew at the end of that month".

Two blocks of features:

- bank: always present, every company has transactions.
- ERP: null when the company had not issued an invoice yet, 39% of companies never do.

Debt and balances are deliberately absent. `debt_products.outstanding` and `balances.balance` are
snapshots taken at extraction, so they only describe month 24 and would leak into every earlier
row. Debt behaviour enters through the `debt_repayment` transaction category instead.
"""

import logging
from pathlib import Path

import duckdb
import pandas as pd

from xray.config import PROCESSED_DATA_DIR, WINDOW_FIRST_MONTH, WINDOW_LAST_MONTH

logger = logging.getLogger(__name__)

TREND_WINDOW_MONTHS = 3

# Additive columns, summed as they are when companies roll up into their group.
_ADDITIVE = (
    "n_tx",
    "inflow",
    "outflow",
    "salary_outflow",
    "tax_outflow",
    "debt_repayment_outflow",
    "fee_outflow",
    "n_counterparties",
    "ar_open",
    "ap_open",
    "ar_overdue",
    "ap_overdue",
    "ar_collected",
    "ap_paid",
    "ar_collected_days",
    "ap_paid_days",
    "n_invoices_issued",
    "n_invoices_received",
)


def _base_sql(tx_path: Path, inv_path: Path, companies_path: Path) -> str:
    """Company-by-month SQL with additive columns only.

    An invoice counts as open at month end when it was issued by then and either was never paid
    or was paid later. `status` and `pending_amount` are never read: both describe the state at
    extraction, not the state at month `t`.
    """
    return f"""
    with months as (
        select unnest(generate_series(
            date '{WINDOW_FIRST_MONTH}', date '{WINDOW_LAST_MONTH}', interval 1 month
        ))::date as month
    ),
    spine as (
        select c.company_id, c.group_id, m.month, last_day(m.month) as month_end
        from read_parquet('{companies_path}') c cross join months m
    ),
    tx as (select * from read_parquet('{tx_path}')),
    inv as (select * from read_parquet('{inv_path}')),
    tx_month as (
        select
            company_id,
            month::date as month,
            count(*) as n_tx,
            count(distinct counterparty_id) as n_counterparties,
            sum(case when amount > 0 then amount else 0 end) as inflow,
            sum(case when amount < 0 then -amount else 0 end) as outflow,
            sum(case when amount < 0 and category = 'salary' then -amount else 0 end)
                as salary_outflow,
            sum(case when amount < 0 and category = 'tax' then -amount else 0 end)
                as tax_outflow,
            sum(case when amount < 0 and category = 'debt_repayment' then -amount else 0 end)
                as debt_repayment_outflow,
            sum(case when amount < 0 and category = 'fee' then -amount else 0 end)
                as fee_outflow
        from tx group by 1, 2
    ),
    erp_start as (
        select company_id, min(issuance_date) as first_invoice from inv group by 1
    ),
    inv_open as (
        select
            s.company_id, s.month,
            sum(case when i.side = 'receivable' then abs(i.amount) else 0 end) as ar_open,
            sum(case when i.side = 'payable' then abs(i.amount) else 0 end) as ap_open,
            sum(case when i.side = 'receivable' and i.due_date < s.month_end
                     then abs(i.amount) else 0 end) as ar_overdue,
            sum(case when i.side = 'payable' and i.due_date < s.month_end
                     then abs(i.amount) else 0 end) as ap_overdue
        from spine s join inv i
            on i.company_id = s.company_id
           and i.issuance_date <= s.month_end
           and (i.payment_date is null or i.payment_date > s.month_end)
        group by 1, 2
    ),
    inv_settled as (
        select
            company_id,
            date_trunc('month', payment_date)::date as month,
            sum(case when side = 'receivable' then abs(amount) else 0 end) as ar_collected,
            sum(case when side = 'payable' then abs(amount) else 0 end) as ap_paid,
            sum(case when side = 'receivable'
                     then abs(amount) * date_diff('day', issuance_date, payment_date)
                     else 0 end) as ar_collected_days,
            sum(case when side = 'payable'
                     then abs(amount) * date_diff('day', issuance_date, payment_date)
                     else 0 end) as ap_paid_days
        from inv
        -- 3% of paid invoices are stamped as paid before they were issued, down to -2139 days.
        -- One of those with a large amount flips a whole month's weighted DSO negative.
        where payment_date is not null and payment_date >= issuance_date
        group by 1, 2
    ),
    inv_issued as (
        select
            company_id,
            date_trunc('month', issuance_date)::date as month,
            count(*) filter (where side = 'receivable') as n_invoices_issued,
            count(*) filter (where side = 'payable') as n_invoices_received
        from inv where issuance_date is not null group by 1, 2
    )
    select
        s.company_id, s.group_id, s.month,
        coalesce(e.first_invoice <= s.month_end, false) as has_erp,
        t.n_tx is not null as is_covered,
        coalesce(t.n_tx, 0) as n_tx,
        coalesce(t.n_counterparties, 0) as n_counterparties,
        coalesce(t.inflow, 0) as inflow,
        coalesce(t.outflow, 0) as outflow,
        coalesce(t.salary_outflow, 0) as salary_outflow,
        coalesce(t.tax_outflow, 0) as tax_outflow,
        coalesce(t.debt_repayment_outflow, 0) as debt_repayment_outflow,
        coalesce(t.fee_outflow, 0) as fee_outflow,
        coalesce(o.ar_open, 0) as ar_open,
        coalesce(o.ap_open, 0) as ap_open,
        coalesce(o.ar_overdue, 0) as ar_overdue,
        coalesce(o.ap_overdue, 0) as ap_overdue,
        coalesce(p.ar_collected, 0) as ar_collected,
        coalesce(p.ap_paid, 0) as ap_paid,
        coalesce(p.ar_collected_days, 0) as ar_collected_days,
        coalesce(p.ap_paid_days, 0) as ap_paid_days,
        coalesce(i.n_invoices_issued, 0) as n_invoices_issued,
        coalesce(i.n_invoices_received, 0) as n_invoices_received
    from spine s
    left join tx_month t on t.company_id = s.company_id and t.month = s.month
    left join inv_open o on o.company_id = s.company_id and o.month = s.month
    left join inv_settled p on p.company_id = s.company_id and p.month = s.month
    left join inv_issued i on i.company_id = s.company_id and i.month = s.month
    left join erp_start e on e.company_id = s.company_id
    """


def _finalize_sql(source: str, key: str) -> str:
    """Add ratios, trends and coverage to an additive base, per entity in month order.

    Ratios are recomputed from the summed numerators rather than averaged, so a group's DSO is
    weighted by invoice value and not by how many subsidiaries it has.
    """
    win = f"partition by {key} order by month"
    return f"""
    select *,
        inflow - outflow as net_flow,
        avg(inflow) over ({win} rows between {TREND_WINDOW_MONTHS - 1} preceding and current row)
            as inflow_{TREND_WINDOW_MONTHS}m,
        avg(inflow - outflow) over (
            {win} rows between {TREND_WINDOW_MONTHS - 1} preceding and current row
        ) as net_flow_{TREND_WINDOW_MONTHS}m,
        inflow - lag(inflow) over ({win}) as inflow_mom,
        case when ar_open > 0 then ar_overdue / ar_open end as ar_overdue_ratio,
        case when ap_open > 0 then ap_overdue / ap_open end as ap_overdue_ratio,
        case when ar_collected > 0 then ar_collected_days / ar_collected end as dso_days,
        case when ap_paid > 0 then ap_paid_days / ap_paid end as dpo_days,
        case when outflow > 0 then inflow / outflow end as inflow_cover,
        sum(case when is_covered then 1 else 0 end) over (
            {win} rows between unbounded preceding and current row
        ) as months_observed
    from ({source})
    """


def build(processed_dir: Path = PROCESSED_DATA_DIR) -> dict[str, pd.DataFrame]:
    """Build the company and group panels from the cleaned parquet tables.

    Args:
        processed_dir: Directory holding the output of ``xray.pipeline.clean``.

    Returns:
        The two panels, keyed ``"panel_company"`` and ``"panel_group"``.
    """
    base = _base_sql(
        processed_dir / "transactions.parquet",
        processed_dir / "invoices.parquet",
        processed_dir / "companies.parquet",
    )
    con = duckdb.connect()
    company = con.sql(_finalize_sql(base, "company_id")).df()

    additive = ", ".join(f"sum({c}) as {c}" for c in _ADDITIVE)
    group_base = f"""
        select group_id, month,
            count(*) as n_companies,
            bool_or(has_erp) as has_erp,
            bool_or(is_covered) as is_covered,
            {additive}
        from ({base}) group by 1, 2
    """
    group = con.sql(_finalize_sql(group_base, "group_id")).df()
    con.close()
    return {"panel_company": company, "panel_group": group}


def main() -> None:
    """Build both panels and write them to data/processed."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name, df in build().items():
        path = PROCESSED_DATA_DIR / f"{name}.parquet"
        df.to_parquet(path, index=False)
        logger.info("%-16s %6d rows x %2d cols -> %s", name, len(df), df.shape[1], path)


if __name__ == "__main__":
    main()

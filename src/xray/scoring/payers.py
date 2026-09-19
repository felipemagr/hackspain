"""Serving table `payers`: how each customer of a group pays, as of each month.

Built from the group's own receivable invoices. Counterparty ids do not join to the dataset's
companies, so a customer is judged only by how it has paid this group. As of month t an invoice
counts as open when it was paid after t or never: `status` and `pending_amount` describe
extraction day and are never read. Amounts arrive in euros from `xray.pipeline.clean`.
"""

import logging

import duckdb

from xray.config import PROCESSED_DATA_DIR
from xray.settings import get_settings

logger = logging.getLogger(__name__)

# A customer needs this many paid invoices before its lateness means anything.
MIN_PAID_INVOICES = 6
RECENT_MONTHS = 6
# Score: 100, minus 1.5 points per day late (capped at 60 days),
# minus up to 10 for overdue exposure.
POINTS_PER_DAY_LATE = 1.5
MAX_DAYS_LATE = 60
MAX_OVERDUE_PENALTY = 10
# Rows kept per group and month: the largest customers, plus whoever owes the most overdue.
TOP_BY_BILLING = 12
TOP_BY_OVERDUE = 5

QUERY = f"""
with months as (
    select distinct month::date as month,
        (month + interval 1 month - interval 1 day)::date as month_end
    from read_parquet('{{scores}}')
),
inv as (
    select group_id, counterparty_id, issuance_date::date as issued, due_date::date as due,
           payment_date::date as paid, abs(amount) as amt
    from read_parquet('{{invoices}}')
    where side = 'receivable' and document_type = 'invoice'
      and counterparty_id is not null and due_date is not null and amount <> 0
),
agg as (
    select v.group_id, m.month, v.counterparty_id,
        sum(amt) filter (where issued > month_end - interval 12 month) as billed_12m_eur,
        sum(amt) filter (where paid is null or paid > month_end) as open_eur,
        sum(amt) filter (where (paid is null or paid > month_end) and due < month_end)
            as overdue_eur,
        max(date_diff('day', due, month_end))
            filter (where (paid is null or paid > month_end) and due < month_end)
            as oldest_overdue_days,
        count(*) filter (where paid <= month_end) as n_paid,
        sum(amt * greatest(date_diff('day', due, paid), 0))
            filter (where paid <= month_end and paid > month_end - interval {RECENT_MONTHS} month)
          / nullif(sum(amt) filter (where paid <= month_end
                                    and paid > month_end - interval {RECENT_MONTHS} month), 0)
          as days_late,
        sum(amt * greatest(date_diff('day', due, paid), 0))
            filter (where paid <= month_end - interval {RECENT_MONTHS} month
                    and paid > month_end - interval {2 * RECENT_MONTHS} month)
          / nullif(sum(amt) filter (where paid <= month_end - interval {RECENT_MONTHS} month
                                    and paid > month_end - interval {2 * RECENT_MONTHS} month), 0)
          as days_late_before
    from months m join inv v on v.issued <= m.month_end
    group by all
),
ranked as (
    select *,
        billed_12m_eur / nullif(sum(billed_12m_eur) over (partition by group_id, month), 0)
            as share_of_billing,
        row_number() over (partition by group_id, month order by billed_12m_eur desc nulls last)
            as by_billing,
        row_number() over (partition by group_id, month order by overdue_eur desc nulls last)
            as by_overdue
    from agg
)
select group_id, month::timestamp as month, counterparty_id,
    'Customer ' || regexp_extract(counterparty_id, '(\\d+)$', 1) as name,
    round(coalesce(billed_12m_eur, 0)) as billed_12m_eur,
    round(coalesce(share_of_billing, 0), 4) as share_of_billing,
    round(coalesce(open_eur, 0)) as open_eur,
    round(coalesce(overdue_eur, 0)) as overdue_eur,
    oldest_overdue_days,
    n_paid,
    round(days_late, 1) as days_late,
    round(days_late - days_late_before, 1) as days_late_change,
    n_paid >= {MIN_PAID_INVOICES} as reliable,
    round(greatest(0, 100
        - {POINTS_PER_DAY_LATE} * least(coalesce(days_late, 0), {MAX_DAYS_LATE})
        - {MAX_OVERDUE_PENALTY} * least(coalesce(overdue_eur, 0) / nullif(billed_12m_eur, 0), 1)
    )) as payer_score
from ranked
where by_billing <= {TOP_BY_BILLING} or (by_overdue <= {TOP_BY_OVERDUE} and overdue_eur > 0)
order by group_id, month, billed_12m_eur desc
"""


def build_payers() -> int:
    """Write data/serving/payers.parquet and return its row count."""
    serving = get_settings().serving_dir
    target = serving / "payers.parquet"
    query = QUERY.format(
        scores=serving / "scores.parquet", invoices=PROCESSED_DATA_DIR / "invoices.parquet"
    )
    with duckdb.connect() as con:
        con.execute(f"copy ({query}) to '{target}' (format parquet)")
        rows = con.execute(f"select count(*) from '{target}'").fetchone()[0]
    logger.info("Wrote %s rows to %s", rows, target)
    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"payers: {build_payers()} rows")

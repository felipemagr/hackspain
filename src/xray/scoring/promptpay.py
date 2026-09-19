"""Serving tables `promptpay` and `promptpay_customers`: what a group can safely pay early.

The question the panel answers: of the receivables falling due inside the next 30, 60 or 90 days,
how much will really land, and how much of it can be used to take a supplier's early payment
discount. An invoice is counted only while it is open and not yet due at month t, so the panel
never reads the future: the collection probability comes from how that customer paid before t.

`p` is empirical, not a model: for an invoice due in `d` days inside a window of `W` days, it is
the share of that customer's earlier paid invoices whose delay was at most `W - d` days. A customer
with fewer than MIN_PAID_INVOICES paid invoices has no usable distribution, and its amount is
reported apart as a thin file rather than counted as cash.

A group whose whole book is already overdue still gets a row, carrying `overdue_eur` alone, so
the page can say where the money went instead of falling silent.

Amounts arrive in euros from `xray.pipeline.clean`.
"""

import logging

import duckdb

from xray.config import PROCESSED_DATA_DIR
from xray.settings import get_settings

logger = logging.getLogger(__name__)

WINDOWS = (30, 60, 90)
# Below this many paid invoices the customer's delay distribution is not worth reading.
MIN_PAID_INVOICES = 6
# Above this many it is a solid file rather than an indicative one.
SOLID_PAID_INVOICES = 12
# Customers shown one by one in the panel; the rest arrive as the group total minus these.
TOP_CUSTOMERS = 10
# How far back an overdue invoice still counts as money someone is chasing. Older than this it is
# a write-off, not a collection, and the dataset's never-paid tail would swamp the figure.
OVERDUE_LOOKBACK_DAYS = 365

# Cumulative windows: what is due within 30 days is also due within 60. `late` is the delay of a
# paid invoice, `days_to_due` how far ahead an open invoice falls due.
_WINDOW_AGG = ",\n        ".join(
    f"""sum(amt) filter (where days_to_due <= {w}) as due_{w}_eur,
        sum(amt * p{w}) filter (where days_to_due <= {w}) as exp_{w}_eur,
        sum(amt * amt * p{w} * (1 - p{w})) filter (where days_to_due <= {w}) as var_{w}"""
    for w in WINDOWS
)

_BASE = """
with months as (
    select distinct month::date as month,
        (month + interval 1 month - interval 1 day)::date as month_end
    from read_parquet('{scores}')
),
rec as (
    select operation_id, group_id, counterparty_id, issuance_date::date as issued,
        due_date::date as due, payment_date::date as paid, abs(amount) as amt
    from read_parquet('{invoices}')
    where side = 'receivable' and document_type = 'invoice'
      and counterparty_id is not null and due_date is not null and amount <> 0
),
hist as (
    select counterparty_id, paid, greatest(date_diff('day', due, paid), 0) as late
    from rec where paid is not null
),
history as (
    select m.month, h.counterparty_id, count(*) as n_paid,
        round(median(h.late), 1) as median_late
    from months m join hist h on h.paid <= m.month_end
    group by all
),
open_inv as (
    select m.month, m.month_end, v.operation_id, v.group_id, v.counterparty_id, v.amt,
        date_diff('day', m.month_end, v.due) as days_to_due
    from months m join rec v
        on v.issued <= m.month_end
       and (v.paid is null or v.paid > m.month_end)
       and v.due > m.month_end
       and v.due <= m.month_end + interval {widest} day
),
priced as (
    select o.month, o.group_id, o.counterparty_id, o.amt, o.days_to_due,
        {probabilities}
    from open_inv o
    left join hist h on h.counterparty_id = o.counterparty_id and h.paid <= o.month_end
    group by all
),
customer as (
    select p.group_id, p.month, p.counterparty_id,
        coalesce(c.n_paid, 0) as n_paid, c.median_late,
        {window_agg}
    from priced p
    left join history c on c.month = p.month and c.counterparty_id = p.counterparty_id
    group by all
),
payable as (
    select m.month, v.group_id, abs(v.amount) as amt,
        date_diff('day', m.month_end, v.due_date::date) as days_to_due
    from months m join read_parquet('{invoices}') v
        on v.issuance_date::date <= m.month_end
       and (v.payment_date is null or v.payment_date::date > m.month_end)
       and v.due_date::date > m.month_end
       and v.due_date::date <= m.month_end + interval {widest} day
    where v.side = 'payable' and v.document_type = 'invoice'
      and v.due_date is not null and v.amount <> 0
)
"""

_PROBABILITIES = ",\n        ".join(
    f"coalesce(avg(case when h.late <= {w} - o.days_to_due then 1.0 else 0.0 end), 0) as p{w}"
    for w in WINDOWS
)

# One row per group, month and window: the headline figures the panel opens with.
GROUP_QUERY = (
    _BASE
    + """
, windows as (select unnest({windows}) as window_days)
, receivable as (
    select c.group_id, c.month, w.window_days,
        sum(case w.window_days {due_case} end) as due_eur,
        sum(case when c.n_paid >= {min_paid} then case w.window_days {exp_case} end else 0 end)
            as expected_eur,
        sum(case when c.n_paid >= {min_paid} then case w.window_days {var_case} end else 0 end)
            as variance,
        sum(case when c.n_paid < {min_paid} then case w.window_days {due_case} end else 0 end)
            as thin_eur,
        count(*) filter (where case w.window_days {due_case} end > 0) as n_customers,
        count(*) filter (where c.n_paid < {min_paid} and case w.window_days {due_case} end > 0)
            as n_thin
    from customer c cross join windows w
    group by all
)
, supplier as (
    select p.group_id, w.window_days,
        p.month, count(*) filter (where p.days_to_due <= w.window_days) as payable_n,
        sum(p.amt) filter (where p.days_to_due <= w.window_days) as payable_eur,
        sum(p.amt * p.days_to_due) filter (where p.days_to_due <= w.window_days)
            / nullif(sum(p.amt) filter (where p.days_to_due <= w.window_days), 0) as payable_days
    from payable p cross join windows w
    group by all
)
, overdue as (
    select m.month, v.group_id, sum(v.amt) as overdue_eur, count(*) as overdue_n
    from months m join rec v
        on v.issued <= m.month_end
       and (v.paid is null or v.paid > m.month_end)
       and v.due <= m.month_end
       and v.due > m.month_end - interval {overdue_lookback} day
    group by all
)
, keys as (
    select group_id, month, window_days from receivable where due_eur > 0
    union
    select o.group_id, o.month, w.window_days from overdue o cross join windows w
)
select k.group_id, k.month::timestamp as month, k.window_days,
    round(coalesce(r.due_eur, 0)) as due_eur,
    round(coalesce(r.expected_eur, 0)) as expected_eur,
    round(coalesce(r.variance, 0)) as variance,
    round(coalesce(r.thin_eur, 0)) as thin_eur,
    coalesce(r.n_customers, 0) as n_customers,
    coalesce(r.n_thin, 0) as n_thin,
    round(coalesce(o.overdue_eur, 0)) as overdue_eur,
    coalesce(o.overdue_n, 0) as overdue_n,
    coalesce(s.payable_n, 0) as payable_n,
    round(coalesce(s.payable_eur, 0)) as payable_eur,
    round(s.payable_days, 1) as payable_days
from keys k
left join receivable r
    on r.group_id = k.group_id and r.month = k.month and r.window_days = k.window_days
left join supplier s
    on s.group_id = k.group_id and s.month = k.month and s.window_days = k.window_days
left join overdue o on o.group_id = k.group_id and o.month = k.month
order by k.group_id, k.month, k.window_days
"""
)

# One row per group, month and shown customer, widest window first for the ranking.
CUSTOMER_QUERY = (
    _BASE
    + """
, ranked as (
    select c.*,
        row_number() over (partition by c.group_id, c.month order by c.due_{widest}_eur desc)
            as rank
    from customer c
    where c.due_{widest}_eur > 0 and c.n_paid >= {min_paid}
)
select r.group_id, r.month::timestamp as month, r.counterparty_id,
    'Customer ' || regexp_extract(r.counterparty_id, '(\\d+)$', 1) as name,
    r.n_paid, r.median_late,
    r.n_paid >= {solid_paid} as solid,
    {rounded}
from ranked r
where r.rank <= {top}
order by r.group_id, r.month, r.rank
"""
)


def _case(prefix: str) -> str:
    suffix = "_eur" if prefix != "var" else ""
    return " ".join(f"when {w} then c.{prefix}_{w}{suffix}" for w in WINDOWS)


def _format(query: str, serving, **extra) -> str:
    return query.format(
        scores=serving / "scores.parquet",
        invoices=PROCESSED_DATA_DIR / "invoices.parquet",
        widest=max(WINDOWS),
        windows=list(WINDOWS),
        probabilities=_PROBABILITIES,
        window_agg=_WINDOW_AGG,
        min_paid=MIN_PAID_INVOICES,
        solid_paid=SOLID_PAID_INVOICES,
        top=TOP_CUSTOMERS,
        overdue_lookback=OVERDUE_LOOKBACK_DAYS,
        due_case=_case("due"),
        exp_case=_case("exp"),
        var_case=_case("var"),
        rounded=",\n    ".join(
            f"round(coalesce(r.due_{w}_eur, 0)) as due_{w}_eur,"
            f" round(coalesce(r.exp_{w}_eur, 0)) as exp_{w}_eur,"
            f" round(coalesce(r.var_{w}, 0)) as var_{w}"
            for w in WINDOWS
        ),
        **extra,
    )


def build_promptpay() -> tuple[int, int]:
    """Write the two serving parquets and return their row counts."""
    serving = get_settings().serving_dir
    counts = []
    with duckdb.connect() as con:
        # Parallel float summation reorders the addends, which moves a few rounded euros
        # between builds. One thread keeps the committed tables byte-identical.
        con.execute("set threads = 1")
        for name, query in (("promptpay", GROUP_QUERY), ("promptpay_customers", CUSTOMER_QUERY)):
            target = serving / f"{name}.parquet"
            con.execute(f"copy ({_format(query, serving)}) to '{target}' (format parquet)")
            rows = con.execute(f"select count(*) from '{target}'").fetchone()[0]
            logger.info("Wrote %s rows to %s", rows, target)
            counts.append(rows)
    return counts[0], counts[1]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    group_rows, customer_rows = build_promptpay()
    print(f"promptpay: {group_rows} rows, promptpay_customers: {customer_rows} rows")

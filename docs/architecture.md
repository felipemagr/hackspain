# Data architecture

How raw CSVs become the monthly panel everything else reads, why it is built this way, and where
it stops being the right answer. Read `docs/brief.md` first for what we are building.

## 1. The size of the problem

Measured on the real dataset, on one laptop.

| | |
|---|---|
| Raw CSVs | 615 MB (transactions 450, invoices 165, the other seven under 2) |
| Rows | 3.46 M (tx 2,556,437 · inv 897,894 · rest 17,885) |
| `transactions.csv` to parquet, DuckDB | 0.5 s, 450 MB down to 108 MB |
| Full clean step, pandas | 9 s |
| Panel build, DuckDB | 0.7 s |
| Output | 6,000 group rows, 30,864 company rows |

A full rebuild from raw CSV takes about ten seconds. That single fact decides most of what
follows: there is no incremental loading, no orchestrator, no scheduler and no database server,
because none of them would save time worth having.

## 2. Layers

Three layers, each reading only the one above it. A table never reaches across a layer.

| Layer | Directory | Built by | Holds |
|---|---|---|---|
| raw | `data/raw` | nobody, never modified | the nine source CSVs |
| staging | `data/processed` | `xray.clean` | one parquet per source table, cleaned and typed |
| marts | `data/marts` | `xray.cash`, `xray.panel` | business-facing tables, plus `_lineage.json` |

```
data/raw/*.csv
   |
   v  xray.clean            pandas, one pass, fixes the traps in section 5
data/processed/*.parquet    staging: same grain as the source
   |
   +--> xray.cash           rolls balances.csv back into a monthly series
   |      cash_monthly.parquet      1,266 x 24
   |
   v  xray.panel            duckdb, as-of aggregation, consumes cash_monthly
panel_company.parquet       1,286 x 24
panel_group.parquet           250 x 24   <- the contract
   |
   v                        score, explain, monitor, offer, api
```

`make panel` runs it. Make tracks the file dependencies, so an unchanged raw dump rebuilds
nothing and a touched `clean.py` rebuilds from there down.

### Lineage

Every mart table has an entry in `data/marts/_lineage.json` naming the tables it was built from,
the commit that built it, when, and its shape:

```json
"cash_monthly": {
  "built_at": "2026-09-18T21:48:26+00:00",
  "git_commit": "84ba7dc",
  "sources": ["balances", "banking_products", "transactions"],
  "rows": 30384,
  "columns": ["company_id", "month", "cash", "n_cash_accounts", "cash_is_extrapolated"]
}
```

So a number on a chart can be traced to the files behind it without reading the code.

## 3. Parquet is the system of record, DuckDB is a query engine

Never persist a `.duckdb` file. `duckdb.connect()` opens in memory, reads parquet, writes parquet,
closes.

This is not a detail, it is the design. A DuckDB file held open read-write takes an exclusive lock
on the whole database, and a second process is refused even when it asks for read-only:

```
second writer:      IO Error: Could not set lock on file
concurrent reader:  IO Error: Could not set lock on file
```

So the obvious layout, an API container serving from `xray.duckdb` while a build job writes to it,
deadlocks. Keeping state in parquet removes the problem instead of working around it: writers
append files, readers open them, the two never meet.

The rest of the honest case against DuckDB, since we are betting on it:

- No network protocol, no auth, no connection pool. It is embedded, like SQLite, and will not
  become a server.
- No time travel, no CDC, no schema evolution. Delta and Iceberg have those; this does not.
- The storage format is tied to the DuckDB version, which is another reason not to ship a
  `.duckdb` file in an image. Parquet has no such coupling.
- Single node. Irrelevant at 3.46 M rows, relevant to any claim we make on stage.

What it buys, against those: it parses the quoted multi-line CSV correctly, does the whole
join-and-aggregate in under a second, needs no service in the compose file, and leaves the output
readable by pandas, polars or R without anyone reading our Python.

Alternatives weighed and rejected: **Postgres** solves concurrency we do not have and costs a
service plus migrations; **SQLite** is single-writer too and a row store; **Spark, ClickHouse,
Airflow** are for problems two orders of magnitude larger than this one.

## 4. The panel contract

`data/marts/panel_group.parquet`, one row per `(group_id, month)`, 6,000 rows, 24 months from
2024-09 to 2026-08. `panel_company.parquet` is the same schema keyed by `company_id`.

Every value is computed from data at or before that month's last day. A row is what the system
knew at the end of that month.

| Column | Type | |
|---|---|---|
| `group_id`, `month` | str, datetime | Keys |
| `n_companies` | int | Companies in the group |
| `has_erp` | bool | The group had issued an invoice by this month |
| `is_covered` | bool | At least one transaction this month |
| `months_observed` | float | Covered months so far |
| `n_tx`, `n_counterparties` | float | Bank activity |
| `cash` | float | Reconstructed closing balance, checking and saving only |
| `runway_months` | float | `cash / outflow`. Negative when overdrawn |
| `cash_is_extrapolated` | bool | Month precedes the first transaction, so cash is a flat estimate |
| `inflow`, `outflow`, `net_flow` | float | Money in, out, and the difference |
| `salary_outflow`, `tax_outflow`, `debt_repayment_outflow`, `fee_outflow` | float | Outflow by category |
| `inflow_3m`, `net_flow_3m`, `inflow_mom` | float | Trend, not level |
| `inflow_cover` | float | `inflow / outflow` |
| `ar_open`, `ap_open` | float | Receivable and payable still open at month end |
| `ar_overdue`, `ap_overdue` | float | Of those, past due |
| `ar_overdue_ratio`, `ap_overdue_ratio` | float | Overdue over open |
| `ar_collected`, `ap_paid` | float | Settled during the month |
| `dso_days`, `dpo_days` | float | Value-weighted days to settle |
| `n_invoices_issued`, `n_invoices_received` | float | Invoice counts |

The ERP block is null or zero for the 83 groups that never file an invoice, and for any group
before its first one. Check `has_erp` before using it; do not impute across that boundary.

`ar_collected_days` and `ap_paid_days` are the weighted numerators behind `dso_days` and
`dpo_days`. They are in the file so a group's DSO stays weighted by invoice value when companies
roll up, rather than becoming an average of averages. Ignore them otherwise.

### Cash, and why recovering it is not a leak

`balances.csv` is one snapshot at 2026-09-01. Dropping it would throw away the most intuitive
health signal there is, so `xray.cash` rolls it back instead:

```
cash(product, t) = balance(2026-09-01) - flows after t
```

Measured on the real data, the reconstruction holds up: 1,266 of 1,286 companies, median cash flat
near 90k across all 24 months, implied negative balances falling smoothly from 9.6% to 2.6%. No
drift, no blow-up. Runway spans 0.01 months at p10 to 5.0 at p90, so there is real discrimination
in it.

This reads like a leak and is not one. `cash(t)` is the balance that actually stood at month `t`;
later transactions recover that fact rather than describe it with hindsight. Contrast
`invoices.status`, which is a real leak because it stamps July's value onto a March row. The
practical consequence is that the truncation test does not constrain `cash`, so it is checked
separately in `tests/test_cash.py` against a hand-built series.

Two limits, both flagged in the data rather than hidden. Before a company's first transaction the
series is flat at the implied opening balance, marked by `cash_is_extrapolated`, which is 27.6% of
company-months. And the roll-back uses cleaned transactions, so the level carries a small error
from the rows `clean.py` drops. Ranking within a month is unaffected, which is what the score uses.

Only checking and saving accounts count. Cards are a liability, and TPV accounts sweep to zero and
reconstruct 100% negative.

### Still not in the panel, on purpose

`debt_products.outstanding` and `debt_products.granted` are snapshots with no dated movements
behind them, so they cannot be rolled back the way balances can. They describe month 24 and
nothing else. Debt behaviour enters through the dated `debt_repayment` transaction category
instead. Use the snapshots only for a month-24 view, and label it as such.

## 5. What cleaning has to fix

Each of these silently corrupts the score.

**`payment_date` is a placeholder on unpaid invoices.** It equals `due_date` on 96.3% of
`overdue`, 98.3% of `pending` and 98.6% of `payment_in_progress` rows, while `pending_amount`
still equals `amount`. Reading it everywhere scores every overdue invoice as paid exactly on time.
`clean.py` keeps it only when `status = 'paid'`.

**`status` is as-of-extraction.** An invoice that reads `paid` today was `pending` in month 10.
The panel never reads `status` or `pending_amount`; it derives open, overdue and settled from
dates alone.

**The 25th month is one day.** 2026-09 holds only 2026-09-01, 9,242 transactions against 150,667
in August. Left in, every company appears to collapse 94% in the final month. The window ends at
2026-08.

**Coverage ramps 3x.** Active companies go 439 in 2024-09 to 1,229 in 2026-04. Companies onboard
across the window, so "24 months each" is not true per company. Hence `is_covered` and
`months_observed` on every row: level features will otherwise read "onboarded recently" as "dying".

**39% of companies have no ERP data.** All 1,286 have transactions, 785 have invoices, 167 of 250
groups. Hence `has_erp`.

**Multi-line quoted fields.** `description` and `concept` contain commas and newlines, so `wc -l`
and any awk or cut pipeline gives wrong answers. Parse with a real CSV reader.

**3% of paid invoices are paid before they are issued**, down to -2139 days. One of those with a
large amount flips a whole month's weighted DSO negative. The panel drops them from the settled
aggregate.

Smaller: 90.2% of transactions have no `counterparty_id`; `category` is `-` on 25% and is
normalised to `uncategorized`; 4% of transactions carry a non-unit exchange rate.

## 6. Daily data

The challenge ships one static dump. In production the same tables arrive daily, and the rows are
not all append-only:

| Source | Pattern | Key |
|---|---|---|
| `transactions` | append-mostly events, with `status` and `accounting_status` settling later | `transaction_id` |
| `invoices` | **mutable**: `status`, `pending_amount` and `payment_date` change over the invoice's life | `operation_id` |
| `balances`, products | full daily snapshot | `product_id` |

Volume is not the problem, mutation is. Overwriting an invoice row destroys what we knew at month
`t`, so a month scored in March would be using July's knowledge. That breaks the no-leakage
guardrail and, specifically, makes the anticipation bonus a cheat.

`xray.lake` therefore never updates a row. Each extract lands under its own `ingest_date`:

```
data/lake/invoices/ingest_date=2026-09-18/part.parquet
```

and `read_as_of(name, key, date)` replays the latest version of each row that had arrived by then.
Landing a day is an append: no lock, no rewrite, readers never blocked.

This has a useful consequence. Once a month is closed, its as-of features can never change, so a
daily job would only ever recompute the open month, about 250 rows. At this size, rebuild
everything anyway.

## 7. Docker

One image, built from the repo, with the raw data mounted rather than baked in: 615 MB of CSV
does not belong in an image.

```bash
make docker-build      # build xray:latest, 754 MB, about 90 s cold
make docker-pipeline   # run clean + panel over ./data/raw, write ./data/processed, 11 s
```

Point it at a dump somewhere else with `make docker-pipeline RAW_DIR=output`.

The image carries no data, so it rebuilds in seconds when only the source changes. `UV_NO_CACHE=1`
keeps uv's download cache out of the layer, which is worth 480 MB. The 552 MB that remain are
numpy, scipy, pandas, pyarrow and scikit-learn.
The demo image, which is the one that matters in front of the jury, comes when the API lands: it
bakes the processed parquet, which is a few MB, and needs no volume, no network and no database.
Adding it is a second stage on this Dockerfile plus a `CMD`.

## 8. When this stops being right

The full rebuild is ten seconds at 3.46 M rows on one core. It stays under a minute well past
Embat's real customer count, so a nightly full rebuild is a defensible production answer, not just
a hackathon shortcut.

Move off it when any of these becomes true: several writers need the same table at once; the data
no longer fits one machine's memory; the API must serve many concurrent users with sub-second
reads from live state; or retention and schema evolution need managing. The first three point at
Postgres for state with DuckDB kept for analytics. The last points at Iceberg or Delta, both of
which DuckDB can read, so the query layer survives the move.

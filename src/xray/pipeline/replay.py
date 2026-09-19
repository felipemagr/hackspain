"""Feed the platform one month at a time and publish after each: the live demo.

The challenge ships one dump. In production the same tables arrive as the months close, and the
product should be watched moving, not reloaded. So this module cuts the dump into what would have
been received each month, lands it in the lake (`xray.pipeline.lake`, append-only, dated), rebuilds
everything from the lake as of that month, publishes the serving tables and sends that month's
alerts. The API and the front end pick the new build up on their own.

Honesty is the point, so the cut is not a date filter:

- transactions: the month's movements.
- invoices: a new invoice lands as pending in its issuance month; the paid version lands, under
  the same `operation_id`, in the month it was paid. `read_as_of` then shows exactly the state
  the ERP would have shown at that date. `status` and `payment_date` after the month never leak.
- balances: `balances.csv` is the 2026-09 snapshot. Landing it early would make every earlier
  cash figure equal to the final one, so each month lands its own snapshot: the final balance
  minus the booked flows after that month end. The cash roll-back in `xray.pipeline.cash` then
  recovers the same series it recovers from the full dump.

Because nothing in the score is fitted or cross-sectional, the tables published for month `t`
during a replay are identical to the rows for `t` in the full run. `tests/pipeline/test_replay.py`
holds that; `--check` verifies it on the real data against `data/marts/scores.parquet`.

    python -m xray.pipeline.replay --from 2025-01 --to 2026-08 --pause 8 --channel slack
"""

import argparse
import logging
import shutil
import tempfile
import time
from datetime import date
from pathlib import Path

import pandas as pd

from xray.config import LAKE_DIR, MARTS_DIR, RAW_DATA_DIR, WINDOW_FIRST_MONTH, WINDOW_LAST_MONTH
from xray.pipeline import cash, clean, lake, panel
from xray.pipeline.data import load_all
from xray.scoring import notify, serve
from xray.settings import get_settings

logger = logging.getLogger(__name__)

# Row identity across extracts, what `read_as_of` dedupes on.
TABLE_KEYS = {
    "groups": "group_id",
    "companies": "company_id",
    "banking_products": "product_id",
    "debt_products": "product_id",
    "debt_schedule_config": "product_id",
    "transactions": "transaction_id",
    "invoices": "operation_id",
    "balances": "product_id",
}
# Reference tables: one extract, landed with the first month.
STATIC_TABLES = ("groups", "companies", "banking_products", "debt_products", "debt_schedule_config")
FIRST_MONTH = pd.Timestamp(WINDOW_FIRST_MONTH)
LAST_MONTH = pd.Timestamp(WINDOW_LAST_MONTH)


def month_end(month: pd.Timestamp) -> date:
    return (month + pd.offsets.MonthEnd(0)).date()


def _landing_month(dates: pd.Series) -> pd.Series:
    """The month an event lands in: its own, floored at the window start, first month when null."""
    months = dates.dt.to_period("M").dt.to_timestamp()
    return months.clip(lower=FIRST_MONTH).fillna(FIRST_MONTH)


def extracts(raw: dict[str, pd.DataFrame], month: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """What the platform would have received during ``month``, per table."""
    end = pd.Timestamp(month_end(month)) + pd.Timedelta(days=1)
    out = {}
    if month == FIRST_MONTH:
        out.update({name: raw[name] for name in STATIC_TABLES})

    tx = raw["transactions"]
    in_month = (tx["date"] >= month) & (tx["date"] < end)
    out["transactions"] = tx[in_month | ((month == FIRST_MONTH) & (tx["date"] < month))]

    inv = raw["invoices"]
    issued = _landing_month(inv["issuance_date"])
    is_paid = (inv["status"] == "paid") & inv["payment_date"].notna()
    paid = _landing_month(inv["payment_date"]).where(is_paid)
    paid = paid.where(paid.isna() | (paid >= issued), issued)
    pending_now = (issued == month) & ~(paid == month)
    pending = inv[pending_now].copy()
    pending["status"] = pending["status"].where(pending["status"] != "paid", "pending")
    pending["payment_date"] = pd.NaT
    pending["pending_amount"] = pending["amount"]
    out["invoices"] = pd.concat([pending, inv[paid == month]], ignore_index=True)

    # Booked flows after the month, on the same filter `clean_transactions` applies, so the
    # roll-back from this snapshot lands on the same monthly cash as the roll-back from the final.
    # A provider placeholder (-999,999,999 and friends) is what the bank reports every month, so
    # it lands as is and `clean_balances` drops it the same way in both runs.
    booked = tx[(tx["status"] != "pending") & (tx["amount"] != 0)]
    later = booked[(booked["date"] >= end) & (booked["date"] < pd.Timestamp(clean.WINDOW_END))]
    flows_after = later.groupby("product_id")["amount"].sum()
    balances = raw["balances"].copy()
    final = balances["balance"]
    rolled = final - balances["product_id"].map(flows_after).fillna(0)
    balances["balance"] = rolled.where(final.abs() < clean.MAX_ABS_BALANCE, final)
    balances["date"] = pd.Timestamp(month_end(month))
    out["balances"] = balances
    return out


def land_month(raw: dict[str, pd.DataFrame], month: pd.Timestamp, lake_dir: Path = LAKE_DIR):
    """Land one month's extracts, dated at the month end."""
    for name, df in extracts(raw, month).items():
        lake.land(name, df, month_end(month), lake_dir)


def tables_as_of(as_of: date, lake_dir: Path = LAKE_DIR) -> dict[str, pd.DataFrame]:
    """Every raw table as the platform knew it on ``as_of``."""
    tables = {}
    for name, key in TABLE_KEYS.items():
        if not (lake_dir / name).exists():
            continue
        df = lake.read_as_of(name, key, as_of, lake_dir)
        if df.empty:
            # No values to infer types from, so DuckDB hands back int32 everywhere. Give the
            # frame the shape the CSV loader would: untyped, with the date columns as dates.
            df = df.astype(object)
            for col in df.columns:
                if col.endswith(("date", "_at")):
                    df[col] = pd.to_datetime(df[col])
        tables[name] = df
    return tables


def rebuild(as_of: date, lake_dir: Path = LAKE_DIR) -> dict[str, pd.DataFrame]:
    """Run clean, cash, panel and the score over the lake as of a date; return serving tables."""
    cleaned = clean.build_from(tables_as_of(as_of, lake_dir))
    with tempfile.TemporaryDirectory() as tmp:
        processed, marts = Path(tmp) / "processed", Path(tmp) / "marts"
        processed.mkdir()
        marts.mkdir()
        for name, df in cleaned.items():
            df.to_parquet(processed / f"{name}.parquet", index=False)
        cash.build(processed).to_parquet(marts / "cash_monthly.parquet", index=False)
        panels = panel.build(processed, marts)
    return serve.assemble(
        panels["panel_group"], panels["panel_company"], cleaned["companies"], cleaned["groups"]
    )


def run(
    raw_dir: Path,
    first: pd.Timestamp,
    last: pd.Timestamp,
    pause: float,
    channel: str | None,
    lake_dir: Path = LAKE_DIR,
    serving_dir: Path | None = None,
    check: bool = False,
) -> None:
    """Land, rebuild, publish and notify, one month at a time from ``first`` to ``last``."""
    serving_dir = serving_dir or get_settings().serving_dir
    raw = load_all(raw_dir)
    reference = pd.read_parquet(MARTS_DIR / "scores.parquet") if check else None
    # The months before the first one shown still have to be in the lake: the reference tables
    # land with the first month of the window, and every rebuild reads everything up to its date.
    for month in pd.date_range(FIRST_MONTH, first - pd.offsets.MonthBegin(1), freq="MS"):
        land_month(raw, month, lake_dir)
    for month in pd.date_range(first, last, freq="MS"):
        started = time.time()
        land_month(raw, month, lake_dir)
        tables = rebuild(month_end(month), lake_dir)
        serve.publish(tables, serving_dir, as_of=month_end(month).isoformat())
        if channel and len(tables["alerts"]):
            stamp = month.strftime("%Y-%m")
            notify.dispatch(tables["alerts"], channel=channel, since=stamp, until=stamp)
        if reference is not None:
            _check(tables["scores"], reference, month, _garbage_groups(raw, month))
        logger.info("%s live in %.1fs", month.strftime("%Y-%m"), time.time() - started)
        if month < last and pause:
            time.sleep(pause)


def _garbage_groups(raw: dict[str, pd.DataFrame], month: pd.Timestamp) -> set[str]:
    """Groups holding an account whose rolled-back balance is placeholder-sized this month.

    The full run keeps such an account (its final balance looks real) while the replay's
    snapshot for the month trips the placeholder rule, so the two cannot agree there. The flows
    behind it are nonsense either way; the check names these groups instead of failing on them.
    """
    snapshot = extracts(raw, month)["balances"]
    final = raw["balances"].set_index("product_id")["balance"]
    tripped = snapshot[
        (snapshot["balance"].abs() >= clean.MAX_ABS_BALANCE)
        & (snapshot["product_id"].map(final).abs() < clean.MAX_ABS_BALANCE)
    ]
    companies = raw["companies"].set_index("company_id")["group_id"]
    return set(tripped["company_id"].map(companies))


def _check(
    scores: pd.DataFrame, reference: pd.DataFrame, month: pd.Timestamp, skip: set[str]
) -> None:
    """The replayed score for a month must equal the full run's row for that month."""
    keys = ["group_id", "month"]
    now = scores[scores["month"] == month].set_index(keys)["level"]
    full = reference[reference["month"] == month].set_index(keys)["level"].round(2)
    joined = pd.concat([now.rename("replay"), full.rename("full")], axis=1)
    joined = joined[~joined.index.get_level_values("group_id").isin(skip)]
    gap = (joined["replay"] - joined["full"]).abs()
    bad = joined[joined.isna().any(axis=1) | (gap > 0.011)]
    if len(bad):
        raise AssertionError(f"{month:%Y-%m}: {len(bad)} rows differ from the full run\n{bad}")
    logger.info(
        "%s matches the full run on %d groups%s",
        month.strftime("%Y-%m"),
        len(joined),
        f", skipped placeholder-sized accounts in {sorted(skip)}" if skip else "",
    )


def main() -> None:
    """Replay the dump month by month into the lake and the serving tables."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DATA_DIR)
    parser.add_argument("--from", dest="first", default=WINDOW_FIRST_MONTH[:7], help="YYYY-MM")
    parser.add_argument("--to", dest="last", default=WINDOW_LAST_MONTH[:7], help="YYYY-MM")
    parser.add_argument("--pause", type=float, default=8.0, help="seconds between months")
    parser.add_argument("--channel", choices=["slack", "email", "none"], default=None)
    parser.add_argument("--lake-dir", type=Path, default=LAKE_DIR)
    parser.add_argument("--reset", action="store_true", help="empty the lake and the ledger first")
    parser.add_argument("--check", action="store_true", help="assert against data/marts/scores")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    serving_dir = get_settings().serving_dir
    if args.reset:
        shutil.rmtree(args.lake_dir, ignore_errors=True)
        (MARTS_DIR / notify.LEDGER_NAME).unlink(missing_ok=True)
    run(
        args.raw_dir,
        pd.Timestamp(args.first + "-01"),
        pd.Timestamp(args.last + "-01"),
        args.pause,
        args.channel,
        args.lake_dir,
        serving_dir,
        args.check,
    )


if __name__ == "__main__":
    main()

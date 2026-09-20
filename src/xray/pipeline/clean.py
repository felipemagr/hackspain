"""Clean the raw tables and write them as parquet to data/processed.

Every money column leaves this stage in euros, at the average rate of its year (`xray.pipeline.fx`).
Flows and invoices use the year they are dated in, snapshots use the year of the extraction. The
original figure is kept next to it as `*_local` where a later stage needs it, and `currency`
always names the original currency.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from xray.config import PROCESSED_DATA_DIR, RAW_DATA_DIR
from xray.pipeline import fx, names
from xray.pipeline.data import load_all

logger = logging.getLogger(__name__)

WINDOW_START = pd.Timestamp("2024-09-01")
# 2026-09 only has one day of data, so the last usable month is 2026-08.
WINDOW_END = pd.Timestamp("2026-09-01")
MIN_VALID_DATE = pd.Timestamp("2015-01-01")
MAX_VALID_DATE = pd.Timestamp("2028-01-01")
# Balances at or beyond this size are provider placeholders (-999,999,999, 99,999,990,850).
MAX_ABS_BALANCE = 999_000_000

COUNTRY_ALIASES = {
    "ESPAÑA": "ES",
    "ESPANYA": "ES",
    "SPAIN": "ES",
    "PORTUGAL": "PT",
    "ITALIA": "IT",
    "ALEMANIA": "DE",
    "MALAYSIA": "MY",
}
# Documents that represent money owed. Orders and delivery notes are not receivables.
DEBT_DOCUMENT_TYPES = ("invoice", "invoiceGroup", "note", "refund")


def clean_companies(companies: pd.DataFrame) -> pd.DataFrame:
    """Normalize country to ISO codes."""
    out = companies.copy()
    country = out["country"].str.strip().str.upper()
    out["country"] = country.replace(COUNTRY_ALIASES)
    return out


def product_currencies(banking: pd.DataFrame, debt: pd.DataFrame) -> pd.Series:
    """Currency of every account and financing product, indexed by product_id."""
    products = pd.concat([banking[["product_id", "currency"]], debt[["product_id", "currency"]]])
    return products.drop_duplicates("product_id").set_index("product_id")["currency"]


def clean_transactions(
    tx: pd.DataFrame, companies: pd.DataFrame, currencies: pd.Series
) -> pd.DataFrame:
    """Keep booked, non-zero movements inside full months; add group_id, month and euros.

    A movement is in the currency of its account. `amount_local` keeps it, because the cash
    series is rolled back in the account's own currency before it is converted.
    """
    out = tx[(tx["status"] != "pending") & (tx["amount"] != 0)]
    out = out[(out["date"] >= WINDOW_START) & (out["date"] < WINDOW_END)].copy()
    out["category"] = (
        out["category"]
        .fillna("uncategorized")
        .replace({"-": "uncategorized", "cash_settlements": "cash_settlement"})
    )
    out["month"] = out["date"].dt.to_period("M").dt.to_timestamp()
    out = out.merge(companies[["company_id", "group_id", "currency"]], on="company_id")
    # The account's currency, or the company's when the product is not in the dump.
    out["currency"] = out["product_id"].map(currencies).fillna(out["currency"])
    out["amount_local"] = out["amount"]
    out["amount"] = fx.to_eur(out["amount"], out["currency"], out["date"])
    return out


def clean_invoices(inv: pd.DataFrame, companies: pd.DataFrame) -> pd.DataFrame:
    """Keep live debt documents, blank out unusable dates, add side and group_id.

    `payment_date` is kept only for paid invoices: for unpaid ones the source copies `due_date`.
    `status` and `pending_amount` describe the state at extraction (month 24), not at month t.
    """
    out = inv[
        inv["document_type"].isin(DEBT_DOCUMENT_TYPES)
        & (inv["status"] != "cancel")
        & (inv["amount"] != 0)
    ].copy()
    for col in ["issuance_date", "due_date", "payment_date"]:
        out[col] = out[col].where(out[col].between(MIN_VALID_DATE, MAX_VALID_DATE))
    out["payment_date"] = out["payment_date"].where(out["status"] == "paid")
    out["due_date"] = out["due_date"].where(
        out["due_date"] >= out["issuance_date"], out["issuance_date"]
    )
    out["side"] = np.where(out["amount"] > 0, "receivable", "payable")
    for col in ["amount", "pending_amount"]:
        out[col] = fx.to_eur(out[col], out["currency"], out["issuance_date"])
    return out.merge(companies[["company_id", "group_id"]], on="company_id")


def _snapshot_to_eur(df: pd.DataFrame, columns: list[str], currency: pd.Series) -> pd.DataFrame:
    """Convert balances photographed at extraction, at the rate of the extraction year."""
    out = df.copy()
    when = pd.Series(WINDOW_END, index=out.index)
    for col in columns:
        out[col] = fx.to_eur(out[col], currency, when)
    return out


def clean_debt(debt: pd.DataFrame) -> pd.DataFrame:
    """Euros, plus positive `owed` and `limit` (the source stores debt as negative numbers)."""
    out = _snapshot_to_eur(debt, ["granted", "outstanding"], debt["currency"])
    out["owed"] = (-out["outstanding"]).clip(lower=0)
    out["limit"] = out["granted"].abs().replace(0, np.nan)
    return out


def clean_balances(bal: pd.DataFrame, currencies: pd.Series) -> pd.DataFrame:
    """Drop placeholders and convert to euros. `balance_local` feeds the cash series."""
    out = bal[bal["balance"].abs() < MAX_ABS_BALANCE].drop(columns="available")
    out = out.assign(currency=out["product_id"].map(currencies), balance_local=out["balance"])
    return _snapshot_to_eur(out, ["balance", "granted", "liquidity", "countable"], out["currency"])


def clean_debt_schedule(schedule: pd.DataFrame) -> pd.DataFrame:
    return _snapshot_to_eur(
        schedule, ["granted_balance", "outstanding_balance"], schedule["currency"]
    )


def build(raw_dir: Path = RAW_DATA_DIR) -> dict[str, pd.DataFrame]:
    """Clean every table found in ``raw_dir``, keyed by table name."""
    return build_from(load_all(raw_dir))


def build_from(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Clean raw tables already in memory, keyed by table name."""
    groups, companies = names.apply(raw["groups"], clean_companies(raw["companies"]))
    currencies = product_currencies(raw["banking_products"], raw["debt_products"])
    clean = {
        **raw,
        "groups": groups,
        "companies": companies,
        "transactions": clean_transactions(raw["transactions"], companies, currencies),
        "invoices": clean_invoices(raw["invoices"], companies),
        "debt_products": clean_debt(raw["debt_products"]),
        "debt_schedule_config": clean_debt_schedule(raw["debt_schedule_config"]),
        "balances": clean_balances(raw["balances"], currencies),
    }
    for name, df in clean.items():
        logger.info("%-22s %9d -> %9d rows", name, len(raw[name]), len(df))
    return clean


def main() -> None:
    """Clean every table and write it to data/processed as parquet."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name, df in build().items():
        df.to_parquet(PROCESSED_DATA_DIR / f"{name}.parquet", index=False)


if __name__ == "__main__":
    main()

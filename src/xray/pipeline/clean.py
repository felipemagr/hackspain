"""Clean the raw tables and write them as parquet to data/processed."""

import logging

import numpy as np
import pandas as pd

from xray.config import PROCESSED_DATA_DIR
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


def clean_transactions(tx: pd.DataFrame, companies: pd.DataFrame) -> pd.DataFrame:
    """Keep booked, non-zero movements inside full months; add group_id and month."""
    out = tx[(tx["status"] != "pending") & (tx["amount"] != 0)]
    out = out[(out["date"] >= WINDOW_START) & (out["date"] < WINDOW_END)].copy()
    out["category"] = (
        out["category"]
        .fillna("uncategorized")
        .replace({"-": "uncategorized", "cash_settlements": "cash_settlement"})
    )
    out["month"] = out["date"].dt.to_period("M").dt.to_timestamp()
    return out.merge(companies[["company_id", "group_id"]], on="company_id")


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
    return out.merge(companies[["company_id", "group_id"]], on="company_id")


def clean_debt(debt: pd.DataFrame) -> pd.DataFrame:
    """Add positive `owed` and `limit` columns (the source stores debt as negative numbers)."""
    out = debt.copy()
    out["owed"] = (-out["outstanding"]).clip(lower=0)
    out["limit"] = out["granted"].abs().replace(0, np.nan)
    return out


def clean_balances(bal: pd.DataFrame) -> pd.DataFrame:
    """Drop placeholder balances."""
    return bal[bal["balance"].abs() < MAX_ABS_BALANCE].drop(columns="available")


def main() -> None:
    """Clean every table and write it to data/processed as parquet."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raw = load_all()
    companies = clean_companies(raw["companies"])
    clean = {
        **raw,
        "companies": companies,
        "transactions": clean_transactions(raw["transactions"], companies),
        "invoices": clean_invoices(raw["invoices"], companies),
        "debt_products": clean_debt(raw["debt_products"]),
        "balances": clean_balances(raw["balances"]),
    }
    for name, df in clean.items():
        df.to_parquet(PROCESSED_DATA_DIR / f"{name}.parquet", index=False)
        logger.info("%-22s %9d -> %9d rows", name, len(raw[name]), len(df))


if __name__ == "__main__":
    main()

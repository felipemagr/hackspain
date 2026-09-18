"""Project paths and dataset constants."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = Path(os.environ.get("XRAY_DATA_DIR", PROJECT_ROOT / "data" / "raw"))
PROCESSED_DATA_DIR = Path(os.environ.get("XRAY_PROCESSED_DIR", PROJECT_ROOT / "data" / "processed"))
LAKE_DIR = Path(os.environ.get("XRAY_LAKE_DIR", PROJECT_ROOT / "data" / "lake"))
MARTS_DIR = Path(os.environ.get("XRAY_MARTS_DIR", PROJECT_ROOT / "data" / "marts"))

# Cash means money the company can spend. Cards are a liability and TPV accounts sweep to zero.
CASH_ACCOUNT_TYPES = ("checking", "saving")

# Full months only: 2026-09 holds a single day, the balances snapshot.
WINDOW_FIRST_MONTH = "2024-09-01"
WINDOW_LAST_MONTH = "2026-08-01"

TABLES = (
    "groups",
    "companies",
    "banking_products",
    "debt_products",
    "debt_schedule_config",
    "transactions",
    "invoices",
    "balances",
)

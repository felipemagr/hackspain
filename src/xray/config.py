"""Project paths and dataset constants."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = Path(os.environ.get("XRAY_DATA_DIR", PROJECT_ROOT / "data" / "raw"))
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

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

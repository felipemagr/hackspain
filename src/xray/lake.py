"""Land daily extracts as dated parquet partitions, and read back what was known on a date.

The challenge ships one static dump, but the same tables arrive daily in production and rows are
restated: an invoice moves pending to overdue to paid under one `operation_id`. Overwriting it
destroys what we knew at month `t` and turns the anticipation backtest into a cheat: a month
scored in March would be using July's knowledge.

So nothing is ever updated. Each extract lands under its own `ingest_date` and `read_as_of`
replays the latest version of each row that had arrived by a given date. Landing a day is an
append: no lock, no rewrite, and readers are never blocked by the writer.
"""

import logging
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from xray.config import LAKE_DIR

logger = logging.getLogger(__name__)


def partition_path(name: str, ingest_date: date, lake_dir: Path = LAKE_DIR) -> Path:
    """Path of one day's extract of one table."""
    return lake_dir / name / f"ingest_date={ingest_date.isoformat()}" / "part.parquet"


def land(name: str, df: pd.DataFrame, ingest_date: date, lake_dir: Path = LAKE_DIR) -> Path:
    """Write one day's extract of one table. Re-landing the same day overwrites that day only."""
    path = partition_path(name, ingest_date, lake_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info("landed %-14s %8d rows -> %s", name, len(df), path)
    return path


def read_as_of(name: str, key: str, as_of: date, lake_dir: Path = LAKE_DIR) -> pd.DataFrame:
    """Read a table as it was known on `as_of`: the latest version of each row by then.

    Args:
        name: Table name, e.g. ``"invoices"``.
        key: Column identifying a row across extracts, e.g. ``"operation_id"``.
        as_of: Extracts landed after this date are ignored.

    Returns:
        One row per key, without the `ingest_date` partition column.
    """
    glob = f"{lake_dir / name}/**/*.parquet"
    return duckdb.sql(f"""
            select * exclude (ingest_date)
            from read_parquet('{glob}', hive_partitioning = true)
            where ingest_date <= date '{as_of.isoformat()}'
            qualify row_number() over (partition by {key} order by ingest_date desc) = 1
        """).df()

"""Load the challenge CSV tables."""

import logging
from pathlib import Path

import pandas as pd

from xray.config import RAW_DATA_DIR, TABLES

logger = logging.getLogger(__name__)


def load_table(name: str, data_dir: Path = RAW_DATA_DIR) -> pd.DataFrame:
    """Load one table by name, e.g. ``load_table("invoices")``.

    Columns whose name ends in ``date`` or ``_at`` are parsed as datetimes.

    Raises:
        FileNotFoundError: If ``<data_dir>/<name>.csv`` does not exist.
    """
    path = data_dir / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Put the dataset CSVs in {data_dir}.")

    df = pd.read_csv(path, low_memory=False)
    for col in df.columns:
        if col.endswith(("date", "_at")):
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def load_all(data_dir: Path = RAW_DATA_DIR) -> dict[str, pd.DataFrame]:
    """Load every table that is present, keyed by table name."""
    tables = {}
    for name in TABLES:
        try:
            tables[name] = load_table(name, data_dir)
        except FileNotFoundError:
            logger.warning("Table %s is missing in %s", name, data_dir)
    return tables


def main() -> None:
    """Print shape, columns and dtypes of every table found."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    tables = load_all()
    if not tables:
        logger.info("No tables found in %s", RAW_DATA_DIR)
        return
    for name, df in tables.items():
        logger.info("\n== %s: %s rows x %s cols", name, *df.shape)
        logger.info("%s", df.dtypes.to_string())


if __name__ == "__main__":
    main()

"""Export the serving tables as JSON for the web demo.

The Vite app fetches one JSON array per table from ``/data/``. When the API grows real
routes, the fetch layer moves to ``/api/v1`` without the page changing.
"""

import logging
from pathlib import Path

import duckdb

from xray.config import PROJECT_ROOT
from xray.settings import get_settings

logger = logging.getLogger(__name__)

WEB_DATA_DIR = PROJECT_ROOT / "web" / "public" / "data"

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "groups": {"group_id", "name", "sector", "country", "n_companies", "has_erp"},
    "scores": {"group_id", "month", "level", "trend", "compound", "state", "tier"},
    "alerts": {"group_id", "month", "state_from", "state_to", "onset_month"},
    "offers": {"group_id", "month", "eligible", "limit_eur"},
    "actions": {"group_id", "month", "rank", "pillar", "action"},
    "companies": {"company_id", "group_id", "name", "inflow_share", "level"},
    "drivers": {"group_id", "month", "pillar", "score", "contribution"},
}

VALID_STATES = {
    "healthy",
    "stable",
    "weak",
    "improving",
    "bending",
    "falling",
    "bump",
    "not_enough_data",
}
VALID_TIERS = {"healthy", "coping", "vulnerable"}
VALID_PILLARS = {
    "liquidity",
    "cash_generation",
    "payment_discipline",
    "collections",
    "debt_burden",
}

ENUM_CHECKS: dict[str, dict[str, set[str]]] = {
    "scores": {"state": VALID_STATES, "tier": VALID_TIERS},
    "alerts": {
        "state_from": VALID_STATES,
        "state_to": VALID_STATES,
        "driver_1": VALID_PILLARS,
        "driver_2": VALID_PILLARS,
    },
    "actions": {"pillar": VALID_PILLARS},
    "drivers": {"pillar": VALID_PILLARS},
}

FX_RATES_FILE = Path(__file__).with_name("fx_rates.csv")
# Read by the agents through the API, never by the page: not worth shipping as JSON.
API_ONLY = {"payers"}


def _validate(con: duckdb.DuckDBPyConnection, parquet: Path) -> None:
    """Fail loudly if a serving table drifts from what the front end renders."""
    name = parquet.stem
    cols = {r[0] for r in con.execute(f"describe select * from '{parquet}'").fetchall()}
    missing = REQUIRED_COLUMNS.get(name, set()) - cols
    if missing:
        raise ValueError(f"{name}: missing columns {sorted(missing)}")
    for col, allowed in ENUM_CHECKS.get(name, {}).items():
        found = {
            r[0]
            for r in con.execute(
                f"select distinct {col} from '{parquet}' where {col} is not null"
            ).fetchall()
        }
        if not found <= allowed:
            raise ValueError(f"{name}.{col}: unexpected values {sorted(found - allowed)}")


def export_serving() -> list[Path]:
    """Write one JSON array per parquet table in the serving directory."""
    serving_dir = get_settings().serving_dir
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    with duckdb.connect() as con:
        for parquet in sorted(serving_dir.glob("*.parquet")):
            if parquet.stem in API_ONLY:
                continue
            _validate(con, parquet)
            target = WEB_DATA_DIR / f"{parquet.stem}.json"
            con.execute(f"copy (select * from '{parquet}') to '{target}' (format json, array true)")
            written.append(target)
            logger.info("Exported %s -> %s", parquet.name, target.name)
    written.append(_export_usd_rates())
    return written


def _export_usd_rates() -> Path:
    """Dollars per euro by year, for the page's EUR / USD switch."""
    target = WEB_DATA_DIR / "fx.json"
    with duckdb.connect() as con:
        con.execute(
            f"""copy (select year, per_eur as usd_per_eur from '{FX_RATES_FILE}'
            where currency = 'USD' order by year) to '{target}' (format json, array true)"""
        )
    return target


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    written = export_serving()
    print(f"exported {len(written)} tables to {WEB_DATA_DIR}")


if __name__ == "__main__":
    main()

"""Assemble the serving tables the product reads, from the real score, and publish them.

One entry point turns the marts into the tables of `docs/serving-contract.md` and writes them to
`data/serving`. Nothing here is invented: the level comes from `score`, direction and alerts from
`monitor`, the decomposition from `explain`, the offer from `offer`. `mock.py` writes the same
tables from made-up groups and retires once this runs.

Publishing is a swap, not a write in place: the tables land in `.next/` and are moved over the
live ones file by file, then `_version.json` is written last. A reader that polls the version
therefore never fetches a set of tables older than the version it saw, and the API, whose DuckDB
views re-read the parquet on every query, serves the new numbers without a restart.
"""

import json
import logging
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from xray.config import MARTS_DIR, PROCESSED_DATA_DIR
from xray.scoring import explain, offer
from xray.scoring.company_impact import impacts
from xray.scoring.monitor import detect
from xray.scoring.score import score
from xray.settings import get_settings

logger = logging.getLogger(__name__)

KEYS = ["group_id", "month"]
MONTHS_PER_QUARTER = 3
PILLARS = list(explain.PILLAR_WEIGHTS)
VERSION_FILE = "_version.json"
STAGING_DIR = ".next"

# Serving name -> engine name, in the order the contract lists them.
SCORE_COLUMNS = {
    **{c: c for c in KEYS + PILLARS},
    "level_uncapped": "level_uncapped",
    "is_capped": "is_capped",
    "level": "level",
    "coverage": "coverage",
    "buffer_days": "buffer_days",
    "operating_margin": "op_margin",
    "ap_days_beyond_terms": "ap_days_late",
    "ar_days_beyond_terms": "ar_days_late",
    "dscr": "dscr",
    "months_observed": "months_observed",
    "tier": "tier",
    "monthly_inflow_eur": "monthly_inflow_eur",
    "cash_eur": "cash_eur",
    "cash_is_extrapolated": "cash_is_extrapolated",
    "monthly_outflow_eur": "monthly_outflow_eur",
    "monthly_debt_service_eur": "monthly_debt_service_eur",
    "net_flow_volatility_eur": "net_flow_volatility_eur",
    "level_smooth": "level_smooth",
    "trend": "trend",
    "compound": "compound",
    "state": "state",
}
INVESTABLE_SCORE_COLUMNS = {
    "cash_eur",
    "cash_is_extrapolated",
    "monthly_outflow_eur",
    "monthly_debt_service_eur",
    "net_flow_volatility_eur",
}


def _with_panel(scores: pd.DataFrame, panel: pd.DataFrame, key: str = "group_id") -> pd.DataFrame:
    """Size and headline columns the score table does not carry itself."""
    cols = [
        "cash",
        "cash_is_extrapolated",
        "opin_3m",
        "opout_3m",
        "opin_12m",
        "opout_12m",
        "debt_service_12m",
        "inflow_op",
        "outflow_op",
        "debt_repayment_outflow",
        "interest_outflow",
    ]
    history = (
        panel.loc[panel["is_covered"], [key, "month"] + cols].sort_values([key, "month"]).copy()
    )
    history["net_flow"] = (
        history["inflow_op"]
        - history["outflow_op"]
        - history["debt_repayment_outflow"]
        - history["interest_outflow"]
    )
    history["net_flow_volatility_eur"] = history.groupby(key, sort=False)["net_flow"].transform(
        lambda s: s.rolling(6, min_periods=3).std()
    )
    out = scores.merge(history, on=[key, "month"], how="left")
    out["monthly_inflow_eur"] = out["opin_3m"] / MONTHS_PER_QUARTER
    out["cash_eur"] = out["cash"]
    out["monthly_outflow_eur"] = out["opout_3m"] / MONTHS_PER_QUARTER
    out["monthly_debt_service_eur"] = out["debt_service_12m"] / 12
    out["dscr"] = np.where(
        out["debt_service_12m"] > 0,
        (out["opin_12m"] - out["opout_12m"]) / out["debt_service_12m"],
        np.nan,
    )
    return out.drop(columns=[c for c in cols if c != "cash_is_extrapolated"] + ["net_flow"])


def _label(table: pd.DataFrame | None, key: str, column: str, ids: pd.Series) -> np.ndarray:
    """``column`` of ``table`` looked up by ``key``, when the dump carries it; else nulls."""
    if table is None or column not in table:
        return np.full(len(ids), None, dtype=object)
    return ids.map(table.drop_duplicates(key).set_index(key)[column]).to_numpy()


def _groups(
    scores: pd.DataFrame, companies: pd.DataFrame, groups: pd.DataFrame | None
) -> pd.DataFrame:
    """One row per group as of its last scored month.

    The challenge dump carries no trading names or sectors, so ``name`` falls back to the id; a
    dump that does carry them (the synthetic demo) shows them.
    """
    last = scores.sort_values("month").groupby("group_id").tail(1)
    ids = last["group_id"]
    country = (
        companies.dropna(subset=["country"])
        .groupby("group_id")["country"]
        .agg(lambda s: s.mode().iat[0])
    )
    names = pd.Series(_label(groups, "group_id", "name", ids)).fillna(ids.reset_index(drop=True))
    return pd.DataFrame(
        {
            "group_id": ids.to_numpy(),
            "name": names.to_numpy(),
            "sector": _label(groups, "group_id", "sector", ids),
            "country": ids.map(country).to_numpy(),
            "n_companies": last["n_companies"].astype(int).to_numpy(),
            "has_erp": last["has_erp"].to_numpy(),
            "annual_revenue_eur": (last["monthly_inflow_eur"] * 12).round(-3).to_numpy(),
        }
    )


def _companies(
    panel_company: pd.DataFrame,
    scores: pd.DataFrame,
    company_scores: pd.DataFrame,
    companies: pd.DataFrame,
) -> pd.DataFrame:
    """Subsidiaries at the group's last scored month: share of inflow, own level, weakest flag.

    ``months_observed`` is the company's own count, so the front end can flag a subsidiary
    whose level rests on a short history even when the group's is long.
    """
    last_month = scores.groupby("group_id")["month"].max().rename("last_month")
    rows = panel_company.merge(last_month, left_on="group_id", right_index=True)
    rows = rows[rows["month"] == rows["last_month"]]
    rows = rows.merge(
        company_scores[["company_id", "month", "level"]], on=["company_id", "month"], how="left"
    )
    group_inflow = rows.groupby("group_id")["opin_3m"].transform("sum")
    rows["inflow_share"] = np.where(group_inflow > 0, rows["opin_3m"] / group_inflow, np.nan)
    weakest = rows.groupby("group_id")["level"].transform("min")
    n_scored = rows.groupby("group_id")["level"].transform("count")
    rows["is_weakest"] = (rows["level"] == weakest) & (n_scored > 1)
    named = pd.Series(_label(companies, "company_id", "name", rows["company_id"]))
    rows["name"] = named.fillna(rows["company_id"].reset_index(drop=True)).to_numpy()
    return rows[
        ["company_id", "group_id", "name", "inflow_share", "level", "is_weakest", "months_observed"]
    ].reset_index(drop=True)


def build(
    marts_dir: Path = MARTS_DIR, processed_dir: Path = PROCESSED_DATA_DIR
) -> dict[str, pd.DataFrame]:
    """Every serving table, keyed by the file name it is written to."""
    return assemble(
        pd.read_parquet(marts_dir / "panel_group.parquet"),
        pd.read_parquet(marts_dir / "panel_company.parquet"),
        pd.read_parquet(processed_dir / "companies.parquet"),
        pd.read_parquet(processed_dir / "groups.parquet"),
    )


def assemble(
    panel: pd.DataFrame,
    panel_company: pd.DataFrame,
    companies: pd.DataFrame,
    groups: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Every serving table from in-memory panels, for callers that never touch the marts."""
    scores = _with_panel(score(panel), panel)
    trajectory, alerts = detect(scores)
    scores = scores.merge(trajectory.drop(columns=["onset_month"]), on=KEYS)

    company_scores = _with_panel(
        score(panel_company, key="company_id"), panel_company, key="company_id"
    )
    company_trajectory, company_alerts = detect(
        company_scores.drop(columns="group_id").rename(columns={"company_id": "group_id"})
    )
    company_scores = company_scores.merge(
        company_trajectory.drop(columns="onset_month").rename(columns={"group_id": "company_id"}),
        on=["company_id", "month"],
    )
    company_alerts = company_alerts.rename(columns={"group_id": "company_id"}).merge(
        company_scores[["company_id", "group_id", "month"]], on=["company_id", "month"]
    )

    serving_scores = scores[list(SCORE_COLUMNS.values())].set_axis(list(SCORE_COLUMNS), axis=1)
    company_columns = ["company_id"] + [
        name for name in SCORE_COLUMNS.values() if name not in INVESTABLE_SCORE_COLUMNS
    ]
    return {
        "groups": _groups(scores, companies, groups),
        "companies": _companies(panel_company, scores, company_scores, companies),
        "scores": _rounded(serving_scores),
        "drivers": _rounded(explain.drivers(scores)),
        "company_scores": _rounded(company_scores[company_columns]),
        "company_drivers": _rounded(
            explain.drivers(company_scores, key="company_id").merge(
                company_scores[["company_id", "group_id", "month"]],
                on=["company_id", "month"],
            )
        ),
        "company_impact": _rounded(impacts(panel, panel_company, scores)),
        "company_alerts": company_alerts,
        "alerts": alerts,
        "offers": offer.offers(scores),
        "actions": offer.actions(scores),
    }


def _rounded(table: pd.DataFrame) -> pd.DataFrame:
    numeric = table.select_dtypes("float").columns
    return table.assign(**{c: table[c].round(2) for c in numeric})


def publish(tables: dict[str, pd.DataFrame], serving_dir: Path, as_of: str | None = None) -> dict:
    """Swap a new set of serving tables in and stamp the version.

    Args:
        tables: Output of ``build`` or ``assemble``.
        serving_dir: The live serving directory the API reads.
        as_of: Last month of data the build saw, ``YYYY-MM-DD``. Defaults to the last scored month.

    Returns:
        The version record written to ``_version.json``.
    """
    staging = serving_dir / STAGING_DIR
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for name, table in tables.items():
        table.to_parquet(staging / f"{name}.parquet", index=False)
    for path in sorted(staging.glob("*.parquet")):
        os.replace(path, serving_dir / path.name)
    staging.rmdir()

    scores = tables["scores"]
    latest = scores["month"].max()
    version = {
        "build_id": datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%f"),
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "as_of": as_of or latest.strftime("%Y-%m-%d"),
        "latest_month": latest.strftime("%Y-%m-%d"),
        "n_groups": int(scores["group_id"].nunique()),
        "n_alerts": int(len(tables["alerts"])),
        "tables": sorted(tables),
    }
    (serving_dir / VERSION_FILE).write_text(json.dumps(version, indent=2) + "\n")
    for name, table in tables.items():
        logger.info("%-10s %6d rows -> %s", name, len(table), serving_dir / f"{name}.parquet")
    logger.info("published build %s, data as of %s", version["build_id"], version["as_of"])
    return version


def main() -> None:
    """Build every serving table and publish it to the configured serving directory."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    publish(build(), get_settings().serving_dir)


if __name__ == "__main__":
    main()

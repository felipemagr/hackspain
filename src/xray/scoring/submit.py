"""Score a directory of challenge CSVs the system has never seen: the hidden-test submission.

The whole chain runs in a scratch directory, so the hidden test never touches `data/`:

    raw CSVs -> clean -> cash -> panel -> level -> trajectory -> predictions

Nothing in the chain is fitted. Anchors and weights are constants, so a group scores the same
whether it arrives alone or with the 250 training groups; `tests/scoring/test_submit.py` holds
that as an invariant. That is the generalisation claim, and it is why this module has no model
file to load.

The submission format is not published yet, so the output is the long form everything else can
be cut from: one row per entity per month with the level, its direction and its state.

    python -m xray.scoring.submit --raw-dir path/to/hidden --out submission/
"""

import argparse
import logging
import tempfile
from pathlib import Path

import pandas as pd

from xray.pipeline import cash, clean, panel
from xray.scoring.monitor import detect
from xray.scoring.score import score
from xray.scoring.serve import _with_panel

logger = logging.getLogger(__name__)

GROUP_COLUMNS = [
    "group_id",
    "month",
    "level",
    "level_smooth",
    "trend",
    "compound",
    "state",
    "tier",
    "coverage",
    "months_observed",
]
COMPANY_COLUMNS = ["company_id", "group_id", "month", "level", "tier", "coverage"]


def panels(raw_dir: Path, work_dir: Path) -> dict[str, pd.DataFrame]:
    """Run the pipeline over ``raw_dir`` into ``work_dir``; return both panels."""
    processed, marts = work_dir / "processed", work_dir / "marts"
    processed.mkdir(parents=True, exist_ok=True)
    marts.mkdir(parents=True, exist_ok=True)
    for name, df in clean.build(raw_dir).items():
        df.to_parquet(processed / f"{name}.parquet", index=False)
    cash.build(processed).to_parquet(marts / "cash_monthly.parquet", index=False)
    return panel.build(processed, marts)


def predict(raw_dir: Path, work_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    """Score every group and company in a raw dump.

    Args:
        raw_dir: Directory holding the challenge CSVs.
        work_dir: Where intermediate parquet lands. A temporary directory when omitted.

    Returns:
        ``groups``: one row per group-month with level, trend, compound, state and tier.
        ``companies``: one row per company-month with level and tier.
    """
    with tempfile.TemporaryDirectory() as tmp:
        built = panels(raw_dir, work_dir or Path(tmp))
    groups = _with_panel(score(built["panel_group"]), built["panel_group"])
    trajectory, _ = detect(groups)
    groups = groups.merge(trajectory.drop(columns=["onset_month"]), on=["group_id", "month"])
    companies = score(built["panel_company"], key="company_id")
    return {
        "groups": _rounded(groups[GROUP_COLUMNS].sort_values(["group_id", "month"])),
        "companies": _rounded(companies[COMPANY_COLUMNS].sort_values(["company_id", "month"])),
    }


def _rounded(table: pd.DataFrame) -> pd.DataFrame:
    numeric = table.select_dtypes("number").columns
    return table.assign(**{c: table[c].round(2) for c in numeric}).reset_index(drop=True)


def main() -> None:
    """Write ``predictions_groups.csv`` and ``predictions_companies.csv``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True, help="the hidden-test CSVs")
    parser.add_argument("--out", type=Path, default=Path("submission"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    for name, table in predict(args.raw_dir).items():
        path = args.out / f"predictions_{name}.csv"
        table.to_csv(path, index=False, date_format="%Y-%m-%d")
        logger.info("%-10s %6d rows -> %s", name, len(table), path)


if __name__ == "__main__":
    main()

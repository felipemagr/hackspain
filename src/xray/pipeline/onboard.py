"""Companies joining the platform, batch by batch, while the rest of the portfolio stays put.

`replay` tells the story along time: one portfolio, months landing one after another. This tells
the other story a bank aggregator lives every week: the portfolio is what it is today, and new
customers connect their accounts. Each batch arrives with its whole history, is scored on the
spot next to everyone already there, and the web and the alert channel pick it up.

The base portfolio is the panel the pipeline already built (`data/marts`, what `make lighthouse`
published). Batches come from a raw dump, are cleaned, rolled and panelled in a scratch
directory, and appended to the base group by group. Nothing in the score is cross-sectional, so
appending panels is exact: a group scores the same on the day it joins as it would alone.

    python -m xray.pipeline.onboard --new data/demo/raw --batches 2 --gap 20 --channel slack
"""

import argparse
import logging
import tempfile
import time
from pathlib import Path

import pandas as pd

from xray.config import MARTS_DIR, PROCESSED_DATA_DIR
from xray.integrations.slack import send_slack
from xray.pipeline import cash, clean, panel
from xray.scoring import serve
from xray.settings import get_settings

logger = logging.getLogger(__name__)

# Kept in step with what `serve.assemble` reads.
PANEL_TABLES = ("panel_group", "panel_company", "companies", "groups")


def load_base(
    marts_dir: Path = MARTS_DIR, processed_dir: Path = PROCESSED_DATA_DIR
) -> dict[str, pd.DataFrame]:
    """The portfolio as the pipeline last built it, or nothing when it never ran."""
    paths = {
        "panel_group": marts_dir / "panel_group.parquet",
        "panel_company": marts_dir / "panel_company.parquet",
        "companies": processed_dir / "companies.parquet",
        "groups": processed_dir / "groups.parquet",
    }
    if not all(p.exists() for p in paths.values()):
        logger.info("no portfolio under %s: starting from an empty one", marts_dir)
        return {name: pd.DataFrame() for name in PANEL_TABLES}
    return {name: pd.read_parquet(path) for name, path in paths.items()}


def panels_for(raw_dir: Path) -> dict[str, pd.DataFrame]:
    """Clean, roll and panel a raw dump in a scratch directory; return the four panel tables."""
    cleaned = clean.build(raw_dir)
    with tempfile.TemporaryDirectory() as tmp:
        processed, marts = Path(tmp) / "processed", Path(tmp) / "marts"
        processed.mkdir()
        marts.mkdir()
        for name, df in cleaned.items():
            df.to_parquet(processed / f"{name}.parquet", index=False)
        cash.build(processed).to_parquet(marts / "cash_monthly.parquet", index=False)
        built = panel.build(processed, marts)
    return {**built, "companies": cleaned["companies"], "groups": cleaned["groups"]}


def batches(group_ids: list[str], n: int) -> list[list[str]]:
    """Split the new groups into ``n`` arrivals, dealt round-robin so each batch is a mix."""
    n = max(1, min(n, len(group_ids)))
    return [group_ids[k::n] for k in range(n)]


def _take(tables: dict[str, pd.DataFrame], group_ids: list[str]) -> dict[str, pd.DataFrame]:
    return {name: df[df["group_id"].isin(group_ids)] for name, df in tables.items()}


def _append(
    base: dict[str, pd.DataFrame], more: dict[str, pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    return {name: pd.concat([base[name], more[name]], ignore_index=True) for name in PANEL_TABLES}


def summary(tables: dict[str, pd.DataFrame], group_ids: list[str]) -> str:
    """One line per newcomer with where the score finds it today, worst news first."""
    names = tables["groups"].set_index("group_id")["name"]
    last = (
        tables["scores"][tables["scores"]["group_id"].isin(group_ids)]
        .sort_values("month")
        .groupby("group_id")
        .tail(1)
    )
    order = {"falling": 0, "bending": 1, "weak": 2, "improving": 3, "stable": 4, "healthy": 5}
    last = last.assign(rank=last["state"].map(order).fillna(9)).sort_values(["rank", "level"])
    lines = [
        f"{names.get(r.group_id, r.group_id)}: {r.level:.0f}, {r.state.replace('_', ' ')}"
        for r in last.itertuples()
    ]
    return f"{len(group_ids)} companies connected. " + "; ".join(lines) + "."


def run(
    new_dir: Path,
    n_batches: int = 2,
    gap: float = 20.0,
    channel: str | None = None,
    marts_dir: Path = MARTS_DIR,
    processed_dir: Path = PROCESSED_DATA_DIR,
    serving_dir: Path | None = None,
) -> list[dict]:
    """Onboard the groups of ``new_dir`` onto the current portfolio in batches.

    Returns:
        The version record of each publish, in order.
    """
    serving_dir = serving_dir or get_settings().serving_dir
    portfolio = load_base(marts_dir, processed_dir)
    arriving = panels_for(new_dir)
    ids = list(dict.fromkeys(arriving["groups"]["group_id"]))
    logger.info(
        "%d groups in the portfolio, %d arriving in %d batches",
        portfolio["groups"]["group_id"].nunique() if len(portfolio["groups"]) else 0,
        len(ids),
        n_batches,
    )
    versions = []
    for k, batch in enumerate(batches(ids, n_batches), start=1):
        if k > 1 and gap:
            time.sleep(gap)
        started = time.time()
        portfolio = _append(portfolio, _take(arriving, batch))
        tables = serve.assemble(
            portfolio["panel_group"],
            portfolio["panel_company"],
            portfolio["companies"],
            portfolio["groups"],
        )
        versions.append(serve.publish(tables, serving_dir))
        text = summary(tables, batch)
        logger.info("batch %d live in %.1fs. %s", k, time.time() - started, text)
        if channel == "slack":
            send_slack(text)
    return versions


def main() -> None:
    """Onboard a raw dump in batches onto the portfolio the pipeline last built."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", type=Path, required=True, help="raw dump of the arriving groups")
    parser.add_argument("--batches", type=int, default=2)
    parser.add_argument("--gap", type=float, default=20.0, help="seconds between batches")
    parser.add_argument("--channel", choices=["slack", "none"], default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    run(args.new, args.batches, args.gap, args.channel)


if __name__ == "__main__":
    main()

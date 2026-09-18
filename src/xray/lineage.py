"""Write mart tables with a manifest recording where each one came from.

Every table in `data/marts` has an entry in `_lineage.json` naming the staging tables it was
built from, the commit that built it, and its shape. A number on a chart can then be traced back
to the files it came from without reading the code.
"""

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from xray.config import MARTS_DIR

logger = logging.getLogger(__name__)

MANIFEST_NAME = "_lineage.json"


def _git_commit() -> str:
    """Short commit hash, or "unknown" when git is unavailable or this is not a checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        logger.warning("Could not read the git commit, recording it as unknown: %s", e)
        return "unknown"
    return result.stdout.strip()


def publish(name: str, df: pd.DataFrame, sources: list[str], marts_dir: Path = MARTS_DIR) -> Path:
    """Write one mart table and record its provenance in the manifest.

    Args:
        name: Table name, written as ``<name>.parquet``.
        df: The table to write.
        sources: Names of the tables this one was built from.
        marts_dir: Destination directory.

    Returns:
        Path of the written parquet file.
    """
    marts_dir.mkdir(parents=True, exist_ok=True)
    path = marts_dir / f"{name}.parquet"
    df.to_parquet(path, index=False)

    manifest_path = marts_dir / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest[name] = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "sources": sources,
        "rows": len(df),
        "columns": list(df.columns),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    logger.info("%-16s %6d rows x %2d cols -> %s", name, len(df), df.shape[1], path)
    return path

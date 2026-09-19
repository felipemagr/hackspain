"""The API's in-memory DuckDB: one view per parquet file in the serving directory."""

from fastapi import FastAPI

from xray.settings import get_settings


def refresh_views(app: FastAPI) -> list[str]:
    """Register a view per parquet file; safe to call at any time.

    A view over a parquet path re-reads the file on every query, so tables rewritten by the
    pipeline are live at once. This only has to run when a file appears or disappears.
    """
    serving_dir = get_settings().serving_dir
    tables = []
    for path in sorted(serving_dir.glob("*.parquet")):
        app.state.db.sql(f"create or replace view {path.stem} as select * from '{path}'")
        tables.append(path.stem)
    for stale in set(app.state.tables) - set(tables):
        app.state.db.sql(f"drop view if exists {stale}")
    app.state.tables = tables
    return tables

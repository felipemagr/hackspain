"""Run the whole pipeline: raw CSVs to the marts.

Three layers, each reading only the layer above it:

    data/raw        the nine source CSVs, never modified
    data/processed  staging, one parquet per source table   (xray.clean)
    data/marts      business-facing tables + _lineage.json  (xray.cash, xray.panel)

Inside the mart layer the order matters: `cash_monthly` is built first because the panels read it.
`_lineage.json` records that edge, so the build order is derivable from the data rather than only
from this docstring.
"""

from xray import cash, clean, panel


def main() -> None:
    """Clean the raw tables, reconstruct cash, then build the panels."""
    clean.main()
    cash.main()
    panel.main()


if __name__ == "__main__":
    main()

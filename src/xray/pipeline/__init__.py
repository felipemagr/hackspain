"""Batch pipeline: raw CSVs to parquet tables to the monthly panel.

Run it with `python -m xray.pipeline`.

Three layers, each reading only the one above it:

    data/raw        the nine source CSVs, never modified
    data/processed  staging, one parquet per source table           (clean)
    data/marts      panel and cash tables + _lineage.json           (cash, panel)

Order: data (load) -> clean -> cash (rolls balances back into a monthly series) -> panel (one row
per group per month, reading cash). lake keeps the daily extracts for as-of reads. lineage writes
the mart tables and records where each came from. Only this package imports pandas.
"""

"""Batch pipeline: raw CSVs to parquet tables to the monthly panel.

Run it with `python -m xray.pipeline`.

Order: data (load) -> clean (parquet in data/processed) -> panel (one row per group per month).
lake keeps the daily extracts for as-of reads. Only this package imports pandas.
"""

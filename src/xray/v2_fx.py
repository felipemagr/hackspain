"""Provisional, lagged annual FX normalization for the local V2 preview."""

from hashlib import sha256
from pathlib import Path

import pandas as pd

FX_PATH = Path(__file__).with_name("v2_fx_rates.csv")
SNAPSHOT_DATE = pd.Timestamp("2026-09-01")


def normalize_tables_eur(
    tables: dict[str, pd.DataFrame],
) -> tuple[dict[str, pd.DataFrame], dict[str, object]]:
    """Copy local-currency tables to EUR using only the preceding year's ECB/peg rate.

    Unsupported amounts become NaN, never zero or an invented parity. This is an
    approximate annual conversion, not historical spot valuation.
    """
    for name, frame in tables.items():
        if "original_currency" in frame or any(c.endswith("_local") for c in frame.columns):
            raise ValueError(f"{name}: expected local input, found prior FX normalization columns")
    result = {name: frame.copy(deep=True) for name, frame in tables.items()}
    rates = pd.read_csv(FX_PATH)
    rates = rates[rates.source.isin(["ecb", "peg"]) & rates.per_eur.gt(0)]
    lookup = rates.set_index(["currency", "year"]).per_eur

    def factors(currency: pd.Series, dates: pd.Series) -> pd.Series:
        keys = pd.MultiIndex.from_arrays([currency, pd.to_datetime(dates).dt.year - 1])
        values = pd.Series(lookup.reindex(keys).to_numpy(), index=currency.index)
        return values.mask(currency.eq("EUR").fillna(False), 1.0)

    companies = result["companies"]
    companies["original_currency"] = companies.currency
    native_rates = factors(companies.currency, pd.Series(SNAPSHOT_DATE, index=companies.index))
    by_company = {
        str(row.company_id): {
            "native_currency": None if pd.isna(row.currency) else str(row.currency),
            "native_currency_supported": bool(pd.notna(native_rates.loc[index])),
            "missing_currencies": [],
            "fx_estimated": False,
            "rows_total": 0,
            "rows_excluded": 0,
            "partial": False,
        }
        for index, row in companies.iterrows()
    }
    companies["currency"] = "EUR"
    registry = pd.concat(
        [tables["banking_products"], tables["debt_products"]], ignore_index=True
    ).set_index("product_id")
    if registry.index.has_duplicates:
        raise ValueError("Product identifiers must be unique across banking and debt products")
    missing: set[str] = set()
    coverage = {"rows_total": 0, "rows_converted": 0, "rows_excluded": 0}
    table_coverage = {}
    specs = {
        "banking_products": ([], None),
        "debt_products": (["outstanding", "granted", "liquidity", "owed", "limit"], None),
        "transactions": (["amount"], "date"),
        "invoices": (["amount", "pending_amount"], "issuance_date"),
        "balances": (["balance"], "date"),
    }
    for name, (amount_columns, date_column) in specs.items():
        frame = result[name]
        currency = (
            frame.product_id.map(registry.currency)
            if name in {"transactions", "balances"}
            else frame.currency
        )
        dates = (
            frame[date_column]
            if date_column is not None
            else pd.Series(SNAPSHOT_DATE, index=frame.index)
        )
        per_eur = factors(currency, dates)
        valid = per_eur.notna()
        frame["original_currency"] = currency
        frame["fx_per_eur"] = per_eur
        frame["fx_rate_year"] = pd.to_datetime(dates).dt.year - 1
        frame["currency"] = currency.astype("string").mask(valid, "EUR")
        for column in amount_columns:
            if column in frame:
                frame[f"{column}_local"] = frame[column]
                frame[column] = frame[column] / per_eur
        entity = (
            frame.company_id if "company_id" in frame else frame.product_id.map(registry.company_id)
        )
        stats = pd.DataFrame(
            {
                "entity": entity.astype("string"),
                "currency": currency.astype("string").fillna("UNKNOWN"),
                "excluded": ~valid,
                "estimated": valid & currency.ne("EUR").fillna(False),
            }
        )
        missing.update(stats.loc[stats.excluded, "currency"])
        counts = {
            "rows_total": len(frame),
            "rows_converted": int(valid.sum()),
            "rows_excluded": int((~valid).sum()),
        }
        table_coverage[name] = counts
        for key, count in counts.items():
            coverage[key] += count
        for company_id, group in stats.groupby("entity", observed=True):
            info = by_company[str(company_id)]
            info["rows_total"] += len(group)
            info["rows_excluded"] += int(group.excluded.sum())
            info["fx_estimated"] |= bool(group.estimated.any())
            info["missing_currencies"] = sorted(
                set(info["missing_currencies"]) | set(group.loc[group.excluded, "currency"])
            )
            info["partial"] = info["rows_excluded"] > 0
    for info in by_company.values():
        if not info["native_currency_supported"]:
            currency = info["native_currency"] or "UNKNOWN"
            info["missing_currencies"] = sorted(set(info["missing_currencies"]) | {currency})
            info["partial"] = True
            missing.add(currency)
    return result, {
        "reporting_currency": "EUR",
        "method": "media anual previa aproximada",
        "provisional": True,
        "source": "origin/main:src/xray/pipeline/fx_rates.csv (ecb/peg only)",
        "source_commit": "d4b21938932cc456e9b5515ee1723cfb00280362",
        "source_sha256": sha256(FX_PATH.read_bytes()).hexdigest(),
        "missing_currencies": sorted(missing),
        "coverage": {
            **coverage,
            "basis": "source row counts, not monetary exposure",
            "ratio": coverage["rows_converted"] / coverage["rows_total"]
            if coverage["rows_total"]
            else None,
            "companies_native_supported": int(native_rates.notna().sum()),
            "companies_total": len(companies),
        },
        "by_table": table_coverage,
        "by_company": by_company,
    }

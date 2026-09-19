"""Shared fixtures: a small synthetic raw dump in the challenge's nine-CSV shape."""

import numpy as np
import pandas as pd
import pytest

MONTHS = pd.date_range("2024-09-01", periods=12, freq="MS")


def _company(company_id: str, group_id: str, rng, scale: float) -> dict[str, pd.DataFrame]:
    """One company with a checking account, a year of monthly flows and a couple of invoices."""
    tx = []
    for i, month in enumerate(MONTHS):
        day = month + pd.Timedelta(days=10)
        tx.append((f"{company_id}_in_{i}", day, scale * rng.uniform(0.8, 1.2), "collection"))
        tx.append((f"{company_id}_out_{i}", day, -scale * rng.uniform(0.7, 1.1), "payment"))
        tx.append((f"{company_id}_sal_{i}", day, -scale * 0.2, "salary"))
    transactions = pd.DataFrame(
        tx, columns=["transaction_id", "date", "amount", "category"]
    ).assign(
        company_id=company_id,
        product_id=f"{company_id}_acc",
        value_date=lambda d: d["date"],
        exchange_rate=1.0,
        status="booked",
        accounting_status="RECONCILED",
        description="x",
        counterparty_id=None,
    )
    invoices = pd.DataFrame(
        {
            "operation_id": [f"{company_id}_inv1", f"{company_id}_inv2"],
            "company_id": company_id,
            "document_type": "invoice",
            "issuance_date": pd.to_datetime(["2025-01-05", "2025-03-05"]),
            "due_date": pd.to_datetime(["2025-02-04", "2025-04-04"]),
            "payment_date": pd.to_datetime(["2025-02-20", "2025-04-04"]),
            "amount": [scale, -scale / 2],
            "pending_amount": 0.0,
            "status": "paid",
            "currency": "EUR",
            "accounting_currency": "EUR",
            "exchange_rate": 1.0,
            "concept": "x",
            "counterparty_id": None,
        }
    )
    return {
        "companies": pd.DataFrame(
            [
                {
                    "company_id": company_id,
                    "group_id": group_id,
                    "country": "ES",
                    "currency": "EUR",
                    "erp": "sap",
                    "created_at": "2024-09-01",
                }
            ]
        ),
        "banking_products": pd.DataFrame(
            [
                {
                    "product_id": f"{company_id}_acc",
                    "company_id": company_id,
                    "label": "CHECKING_01",
                    "type": "checking",
                    "bank_name": "Bank",
                    "service": "svc",
                    "currency": "EUR",
                    "created_at": "2024-09-01",
                }
            ]
        ),
        "balances": pd.DataFrame(
            [
                {
                    "product_id": f"{company_id}_acc",
                    "company_id": company_id,
                    "date": "2026-09-01",
                    "balance": scale * 2,
                    "available": None,
                    "granted": None,
                    "liquidity": None,
                    "countable": None,
                }
            ]
        ),
        "transactions": transactions,
        "invoices": invoices,
    }


def _write_dump(path, groups: dict[str, list[str]], rng):
    """Write a raw dump for the given groups, one company id per entry."""
    path.mkdir(parents=True, exist_ok=True)
    tables = {}
    for group_id, company_ids in groups.items():
        for cid in company_ids:
            for name, df in _company(cid, group_id, rng, scale=rng.uniform(5e4, 5e5)).items():
                tables.setdefault(name, []).append(df)
    for name, frames in tables.items():
        pd.concat(frames).to_csv(path / f"{name}.csv", index=False)
    pd.DataFrame(
        [{"group_id": g, "erp": "sap", "n_companies_in_sample": len(c)} for g, c in groups.items()]
    ).to_csv(path / "groups.csv", index=False)
    empty_debt = pd.DataFrame(
        columns=[
            "product_id",
            "company_id",
            "label",
            "type",
            "bank_name",
            "service",
            "currency",
            "created_at",
            "granted",
            "outstanding",
            "liquidity",
        ]
    )
    empty_debt.to_csv(path / "debt_products.csv", index=False)
    pd.DataFrame(
        columns=["product_id", "company_id", "currency", "granted_balance", "outstanding_balance"]
    ).to_csv(path / "debt_schedule_config.csv", index=False)


@pytest.fixture
def write_dump():
    """``write_dump(path, {"g1": ["c1", "c2"], ...}, seed)`` writes a raw dump to ``path``."""

    def _write(path, groups: dict[str, list[str]], seed: int = 1):
        _write_dump(path, groups, np.random.default_rng(seed))
        return path

    return _write

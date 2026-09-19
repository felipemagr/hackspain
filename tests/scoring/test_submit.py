import numpy as np
import pandas as pd
import pytest

from xray.scoring.submit import predict

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
    pd.DataFrame(columns=["product_id", "company_id"]).to_csv(
        path / "debt_schedule_config.csv", index=False
    )


@pytest.fixture
def dumps(tmp_path):
    """The same three groups as one dump, and the first group on its own."""
    plan = {"g1": ["c1", "c2"], "g2": ["c3"], "g3": ["c4"]}
    _write_dump(tmp_path / "all", plan, np.random.default_rng(1))
    _write_dump(tmp_path / "alone", {"g1": plan["g1"]}, np.random.default_rng(1))
    return tmp_path / "all", tmp_path / "alone"


class TestPredict:
    def test_one_row_per_group_month_and_per_company_month(self, dumps):
        out = predict(dumps[0])
        assert set(out["groups"]["group_id"]) == {"g1", "g2", "g3"}
        assert out["groups"].groupby("group_id").size().eq(len(MONTHS)).all()
        assert set(out["companies"]["company_id"]) == {"c1", "c2", "c3", "c4"}
        assert out["groups"]["level"].between(0, 100).all()

    def test_a_group_scores_the_same_alone_as_in_a_portfolio(self, dumps):
        """Nothing is fitted, so the hidden test cannot move a group's score."""
        together = predict(dumps[0])["groups"].query("group_id == 'g1'").reset_index(drop=True)
        alone = predict(dumps[1])["groups"].reset_index(drop=True)
        pd.testing.assert_frame_equal(together, alone)

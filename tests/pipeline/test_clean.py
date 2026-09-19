import pandas as pd
import pytest

from xray.pipeline import fx
from xray.pipeline.clean import clean_invoices, clean_transactions

COMPANIES = pd.DataFrame({"company_id": ["c1"], "group_id": ["g1"], "currency": ["EUR"]})
NO_PRODUCTS = pd.Series(dtype=str)


def test_transactions_drop_pending_and_partial_month():
    tx = pd.DataFrame(
        {
            "company_id": ["c1"] * 3,
            "product_id": ["p1"] * 3,
            "date": pd.to_datetime(["2025-01-10", "2025-01-11", "2026-09-01"]),
            "amount": [10.0, 20.0, 30.0],
            "status": ["booked", "pending", "booked"],
            "category": ["-", "fee", "fee"],
        }
    )

    out = clean_transactions(tx, COMPANIES, NO_PRODUCTS)

    assert out["amount"].tolist() == [10.0]
    assert out["category"].tolist() == ["uncategorized"]
    assert out["group_id"].tolist() == ["g1"]


def test_invoices_keep_payment_date_only_when_paid():
    inv = pd.DataFrame(
        {
            "company_id": ["c1"] * 3,
            "document_type": ["invoice", "invoice", "purchaseOrder"],
            "status": ["paid", "overdue", "paid"],
            "amount": [100.0, -50.0, 10.0],
            "pending_amount": [0.0, -50.0, 0.0],
            "currency": ["EUR"] * 3,
            "issuance_date": pd.to_datetime(["2025-01-01"] * 3),
            "due_date": pd.to_datetime(["2025-01-31", "1900-01-01", "2025-01-31"]),
            "payment_date": pd.to_datetime(["2025-02-05", "2025-01-31", "2025-01-31"]),
        }
    )

    out = clean_invoices(inv, COMPANIES)

    assert out["side"].tolist() == ["receivable", "payable"]
    assert out["payment_date"].notna().tolist() == [True, False]
    assert out["due_date"].tolist() == [pd.Timestamp("2025-01-31"), pd.Timestamp("2025-01-01")]


def test_amounts_leave_in_euros_at_the_rate_of_their_own_year():
    """A dollar account: the same 100 dollars is worth less in 2026 than in 2024."""
    tx = pd.DataFrame(
        {
            "company_id": ["c1"] * 2,
            "product_id": ["usd_account"] * 2,
            "date": pd.to_datetime(["2024-10-05", "2026-03-05"]),
            "amount": [100.0, 100.0],
            "status": ["booked"] * 2,
            "category": ["fee"] * 2,
        }
    )
    usd = fx.load_rates().query("currency == 'USD'").set_index("year")["per_eur"]

    out = clean_transactions(tx, COMPANIES, pd.Series({"usd_account": "USD"}))

    assert out["amount"].tolist() == pytest.approx([100 / usd[2024], 100 / usd[2026]])
    assert out["amount_local"].tolist() == [100.0, 100.0]
    assert out["currency"].tolist() == ["USD", "USD"]


def test_a_currency_with_no_rate_is_left_alone_and_logged(caplog):
    amounts = fx.to_eur(
        pd.Series([50.0]), pd.Series(["ZZZ"]), pd.Series(pd.to_datetime(["2025-06-01"]))
    )

    assert amounts.tolist() == [50.0]
    assert "No euro rate for ['ZZZ']" in caplog.text

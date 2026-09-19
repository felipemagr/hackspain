import pandas as pd

from xray.pipeline.clean import clean_invoices, clean_transactions

COMPANIES = pd.DataFrame({"company_id": ["c1"], "group_id": ["g1"]})


def test_transactions_drop_pending_and_partial_month():
    tx = pd.DataFrame(
        {
            "company_id": ["c1"] * 3,
            "date": pd.to_datetime(["2025-01-10", "2025-01-11", "2026-09-01"]),
            "amount": [10.0, 20.0, 30.0],
            "status": ["booked", "pending", "booked"],
            "category": ["-", "fee", "fee"],
        }
    )

    out = clean_transactions(tx, COMPANIES)

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
            "issuance_date": pd.to_datetime(["2025-01-01"] * 3),
            "due_date": pd.to_datetime(["2025-01-31", "1900-01-01", "2025-01-31"]),
            "payment_date": pd.to_datetime(["2025-02-05", "2025-01-31", "2025-01-31"]),
        }
    )

    out = clean_invoices(inv, COMPANIES)

    assert out["side"].tolist() == ["receivable", "payable"]
    assert out["payment_date"].notna().tolist() == [True, False]
    assert out["due_date"].tolist() == [pd.Timestamp("2025-01-31"), pd.Timestamp("2025-01-01")]

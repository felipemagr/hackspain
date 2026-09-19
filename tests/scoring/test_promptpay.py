"""`promptpay` builds the early-payment serving tables: window sums, empirical `p`, thin files."""

from types import SimpleNamespace

import pandas as pd
import pytest

from xray.scoring import promptpay

M1, M2 = "2024-09-01", "2024-10-01"


def _invoice(op, cp, side, amount, issued, due, paid=None):
    return {
        "operation_id": op,
        "group_id": "G1",
        "counterparty_id": cp,
        "side": side,
        "amount": amount,
        "issuance_date": pd.Timestamp(issued),
        "due_date": pd.Timestamp(due),
        "payment_date": pd.Timestamp(paid) if paid else None,
        "document_type": "invoice",
    }


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    """Processed and serving dirs the module reads, pointed at tmp_path."""
    processed, serving = tmp_path / "processed", tmp_path / "serving"
    processed.mkdir()
    serving.mkdir()
    monkeypatch.setattr(promptpay, "PROCESSED_DATA_DIR", processed)
    monkeypatch.setattr(promptpay, "get_settings", lambda: SimpleNamespace(serving_dir=serving))
    return processed, serving


def _build(dirs, invoices, months=(M1, M2), payers=None):
    processed, serving = dirs
    pd.DataFrame({"month": pd.to_datetime(list(months))}).to_parquet(
        serving / "scores.parquet", index=False
    )
    pd.DataFrame(invoices).to_parquet(processed / "invoices.parquet", index=False)
    if payers is None:
        payers = pd.DataFrame(
            {
                "group_id": pd.Series(dtype=str),
                "month": pd.Series(dtype="datetime64[ns]"),
                "counterparty_id": pd.Series(dtype=str),
                "payer_score": pd.Series(dtype=float),
            }
        )
    payers.to_parquet(serving / "payers.parquet", index=False)
    promptpay.build_promptpay()
    return pd.read_parquet(serving / "promptpay.parquet")


def test_window_sums_and_thin_file(dirs):
    invoices = [
        # C1: six earlier paid invoices, one 30 days late; open 1000 due 10 days after Sep end.
        *[
            _invoice(f"c1-{i}", "C1", "receivable", 100, "2024-06-01", "2024-07-01", "2024-07-01")
            for i in range(5)
        ],
        _invoice("c1-late", "C1", "receivable", 100, "2024-06-01", "2024-07-01", "2024-07-31"),
        _invoice("c1-open", "C1", "receivable", 1000, "2024-09-05", "2024-10-10"),
        # C2: thin file, three paid; open 500 due 20 days after Sep end.
        *[
            _invoice(f"c2-{i}", "C2", "receivable", 100, "2024-06-01", "2024-07-01", "2024-07-01")
            for i in range(3)
        ],
        _invoice("c2-open", "C2", "receivable", 500, "2024-09-05", "2024-10-20"),
        # C3: solid history; open 300 due 51 days after Sep end: inside 60 and 90, not 30.
        *[
            _invoice(f"c3-{i}", "C3", "receivable", 100, "2024-06-01", "2024-07-01", "2024-07-01")
            for i in range(6)
        ],
        _invoice("c3-open", "C3", "receivable", 300, "2024-09-20", "2024-11-20"),
        # Already due at September end: excluded, chasing it is a different panel.
        _invoice("old", "C1", "receivable", 9000, "2024-08-01", "2024-09-15"),
        # A supplier bill 15 days ahead, payable side carries a negative amount.
        _invoice("sup", "S1", "payable", -800, "2024-09-05", "2024-10-15"),
    ]
    out = _build(dirs, invoices)
    sep = out[out.month == pd.Timestamp(M1)].set_index("window_days")

    assert len(out) == 6  # two months x three windows, nothing due later
    assert sep.loc[30, "due_eur"] == 1500
    assert sep.loc[60, "due_eur"] == 1800
    # p for C1's open invoice: due in 10 days, window 30 needs delay <= 20 -> 5 of 6; 60 -> 6 of 6.
    assert sep.loc[30, "expected_eur"] == pytest.approx(5000 / 6, abs=1)
    assert sep.loc[60, "expected_eur"] == 1000 + 300
    assert sep.loc[30, "variance"] == pytest.approx(1e6 * (5 / 6) * (1 / 6), rel=1e-3)
    assert sep.loc[30, "thin_eur"] == 500
    assert sep.loc[30, "n_customers"] == 2
    assert sep.loc[30, "n_thin"] == 1
    assert sep.loc[30, "payable_n"] == 1
    assert sep.loc[30, "payable_eur"] == 800
    assert sep.loc[30, "payable_days"] == 15
    # The page's split always adds back to the amount due.
    for _, r in sep.iterrows():
        risk_discounted = r.due_eur - r.thin_eur - r.expected_eur
        assert r.expected_eur + risk_discounted + r.thin_eur == pytest.approx(r.due_eur)

    # October: the September bills are already due and drop out; only C3's invoice remains.
    oct_row = out[(out.month == pd.Timestamp(M2)) & (out.window_days == 30)].iloc[0]
    assert oct_row.due_eur == 300
    assert oct_row.expected_eur == 300
    assert oct_row.thin_eur == 0
    assert oct_row.payable_n == 0


def test_customers_table(dirs):
    invoices = [
        *[
            _invoice(f"c1-{i}", "C1", "receivable", 100, "2024-06-01", "2024-07-01", "2024-07-01")
            for i in range(6)
        ],
        _invoice("c1-open", "C1", "receivable", 1000, "2024-09-05", "2024-10-10"),
        *[
            _invoice(f"c2-{i}", "C2", "receivable", 100, "2024-06-01", "2024-07-01", "2024-07-01")
            for i in range(3)
        ],
        _invoice("c2-open", "C2", "receivable", 500, "2024-09-05", "2024-10-20"),
    ]
    payers = pd.DataFrame(
        {
            "group_id": ["G1"],
            "month": [pd.Timestamp(M1)],
            "counterparty_id": ["C1"],
            "payer_score": [77.0],
        }
    )
    _build(dirs, invoices, payers=payers)
    processed, serving = dirs
    customers = pd.read_parquet(serving / "promptpay_customers.parquet")

    # The thin file never gets a row; the payer score is joined, not recomputed.
    assert list(customers.counterparty_id) == ["C1"]
    assert customers.iloc[0].payer_score == 77.0
    assert not customers.iloc[0].solid

import pandas as pd
import pytest

from xray.panel import build

M1, M2, M3 = "2024-09-01", "2024-10-01", "2024-11-01"


def _write(tmp_path, companies, transactions, invoices):
    """Write the three cleaned tables the panel reads."""
    for name, df in [
        ("companies", companies),
        ("transactions", transactions),
        ("invoices", invoices),
    ]:
        df.to_parquet(tmp_path / f"{name}.parquet", index=False)
    return tmp_path


def _tx(company_id, month, amount, category="payment"):
    return {
        "company_id": company_id,
        "month": pd.Timestamp(month),
        "amount": amount,
        "category": category,
        "counterparty_id": "cp1",
    }


def _invoice(company_id, side, amount, issued, due, paid=None):
    return {
        "company_id": company_id,
        "side": side,
        "amount": amount,
        "issuance_date": pd.Timestamp(issued),
        "due_date": pd.Timestamp(due),
        "payment_date": pd.Timestamp(paid) if paid else pd.NaT,
    }


@pytest.fixture
def one_company(tmp_path):
    """One company, one invoice issued in M1 and paid 40 days later in M2."""
    companies = pd.DataFrame([{"company_id": "c1", "group_id": "g1"}])
    transactions = pd.DataFrame([_tx("c1", M1, 1000.0), _tx("c1", M2, -400.0)])
    invoices = pd.DataFrame(
        [_invoice("c1", "receivable", 500.0, "2024-09-10", "2024-10-10", "2024-10-20")]
    )
    return _write(tmp_path, companies, transactions, invoices)


class TestAsOf:
    def test_invoice_is_open_until_it_is_paid(self, one_company):
        panel = build(one_company)["panel_group"].set_index("month")

        assert panel.loc[M1, "ar_open"] == 500.0
        assert panel.loc[M2, "ar_open"] == 0.0
        assert panel.loc[M2, "dso_days"] == 40.0

    def test_erp_block_is_absent_before_the_first_invoice(self, tmp_path):
        companies = pd.DataFrame([{"company_id": "c1", "group_id": "g1"}])
        transactions = pd.DataFrame([_tx("c1", M1, 100.0)])
        invoices = pd.DataFrame([_invoice("c1", "receivable", 500.0, "2024-11-10", "2024-12-10")])
        panel = build(_write(tmp_path, companies, transactions, invoices))["panel_group"].set_index(
            "month"
        )

        assert not panel.loc[M1, "has_erp"]
        assert panel.loc[M3, "has_erp"]
        assert pd.isna(panel.loc[M1, "dso_days"])

    def test_month_without_transactions_is_marked_uncovered(self, one_company):
        panel = build(one_company)["panel_group"].set_index("month")

        assert panel.loc[M1, "is_covered"]
        assert not panel.loc[M3, "is_covered"]
        assert panel.loc[M3, "months_observed"] == 2


class TestNoLeakage:
    """A row for month t must not change when everything after t is removed."""

    @pytest.mark.parametrize("cutoff", [M1, M2, M3])
    def test_row_matches_a_rebuild_that_never_saw_the_future(self, one_company, cutoff):
        full = build(one_company)["panel_group"].set_index("month").loc[cutoff]

        month_end = pd.Timestamp(cutoff) + pd.offsets.MonthEnd(0)
        tx = pd.read_parquet(one_company / "transactions.parquet")
        inv = pd.read_parquet(one_company / "invoices.parquet")
        tx[tx["month"] <= month_end].to_parquet(one_company / "transactions.parquet", index=False)
        past = inv[inv["issuance_date"] <= month_end].copy()
        past["payment_date"] = past["payment_date"].where(past["payment_date"] <= month_end)
        past.to_parquet(one_company / "invoices.parquet", index=False)

        truncated = build(one_company)["panel_group"].set_index("month").loc[cutoff]

        pd.testing.assert_series_equal(full, truncated, check_names=False)


class TestGroupRollup:
    def test_group_dso_is_weighted_by_invoice_value(self, tmp_path):
        companies = pd.DataFrame(
            [
                {"company_id": "c1", "group_id": "g1"},
                {"company_id": "c2", "group_id": "g1"},
            ]
        )
        transactions = pd.DataFrame([_tx("c1", M1, 100.0), _tx("c2", M1, 100.0)])
        invoices = pd.DataFrame(
            [
                _invoice("c1", "receivable", 900.0, "2024-09-01", "2024-09-30", "2024-09-11"),
                _invoice("c2", "receivable", 100.0, "2024-09-01", "2024-09-30", "2024-09-21"),
            ]
        )
        panel = build(_write(tmp_path, companies, transactions, invoices))["panel_group"]

        # 10 days on 900 and 20 days on 100 is 11 days, not the 15 a plain average would give.
        assert panel.set_index("month").loc[M1, "dso_days"] == 11.0

    def test_group_is_covered_when_any_company_is(self, tmp_path):
        companies = pd.DataFrame(
            [
                {"company_id": "c1", "group_id": "g1"},
                {"company_id": "c2", "group_id": "g1"},
            ]
        )
        transactions = pd.DataFrame([_tx("c1", M1, 100.0)])
        invoices = pd.DataFrame([_invoice("c1", "receivable", 1.0, M1, M1)]).iloc[0:0]
        panel = build(_write(tmp_path, companies, transactions, invoices))["panel_group"].set_index(
            "month"
        )

        assert panel.loc[M1, "is_covered"]
        assert panel.loc[M1, "n_companies"] == 2

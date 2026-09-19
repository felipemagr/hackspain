import pandas as pd
import pytest

from xray.pipeline import fx
from xray.pipeline.cash import build

M1, M2, M3 = "2024-09-01", "2024-10-01", "2024-11-01"
FINAL_BALANCE = 1000.0


@pytest.fixture
def staging(tmp_path):
    """One checking account ending at 1000, after +100 in M2 and -300 in M3.

    The implied opening balance is therefore 1200, and the series runs 1200, 1300, 1000.
    """
    pd.DataFrame(
        [
            {"product_id": "p1", "type": "checking", "currency": "EUR"},
            {"product_id": "p2", "type": "card", "currency": "EUR"},
            {"product_id": "p3", "type": "tpv", "currency": "EUR"},
        ]
    ).to_parquet(tmp_path / "banking_products.parquet", index=False)

    pd.DataFrame(
        [
            {"product_id": "p1", "company_id": "c1", "balance_local": FINAL_BALANCE},
            {"product_id": "p2", "company_id": "c1", "balance_local": 500.0},
            {"product_id": "p3", "company_id": "c1", "balance_local": 700.0},
        ]
    ).to_parquet(tmp_path / "balances.parquet", index=False)

    pd.DataFrame(
        [
            {
                "product_id": "p1",
                "company_id": "c1",
                "month": pd.Timestamp(M2),
                "amount_local": 100.0,
            },
            {
                "product_id": "p1",
                "company_id": "c1",
                "month": pd.Timestamp(M3),
                "amount_local": -300.0,
            },
            {
                "product_id": "p2",
                "company_id": "c1",
                "month": pd.Timestamp(M2),
                "amount_local": -50.0,
            },
        ]
    ).to_parquet(tmp_path / "transactions.parquet", index=False)
    return tmp_path


class TestReconstruction:
    def test_series_walks_back_from_the_snapshot(self, staging):
        cash = build(staging).set_index("month")["cash"]

        assert cash.loc[M1] == 1200.0
        assert cash.loc[M2] == 1300.0
        assert cash.loc[M3] == FINAL_BALANCE

    def test_last_month_equals_the_snapshot(self, staging):
        cash = build(staging)

        assert cash.sort_values("month").iloc[-1]["cash"] == FINAL_BALANCE

    def test_only_cash_accounts_count(self, staging):
        """The card and TPV balances would add 1200 if they were treated as cash."""
        cash = build(staging)

        assert (cash["n_cash_accounts"] == 1).all()


class TestExtrapolation:
    def test_months_before_the_first_transaction_are_flagged(self, staging):
        flagged = build(staging).set_index("month")["cash_is_extrapolated"]

        assert flagged.loc[M1]
        assert not flagged.loc[M2]
        assert not flagged.loc[M3]

    def test_a_company_that_never_transacts_is_flagged_throughout(self, tmp_path):
        pd.DataFrame([{"product_id": "p1", "type": "checking", "currency": "EUR"}]).to_parquet(
            tmp_path / "banking_products.parquet", index=False
        )
        pd.DataFrame(
            [{"product_id": "p1", "company_id": "c1", "balance_local": FINAL_BALANCE}]
        ).to_parquet(tmp_path / "balances.parquet", index=False)
        pd.DataFrame([], columns=["product_id", "company_id", "month", "amount_local"]).to_parquet(
            tmp_path / "transactions.parquet", index=False
        )

        cash = build(tmp_path)

        assert cash["cash_is_extrapolated"].all()
        assert (cash["cash"] == FINAL_BALANCE).all()


def test_a_dollar_account_is_rolled_in_dollars_then_converted_at_each_year(staging):
    """Same flows as the euro account. Rolling euros instead would shift 2024 by the rate gap."""
    products = pd.read_parquet(staging / "banking_products.parquet")
    products.loc[products["product_id"] == "p1", "currency"] = "USD"
    products.to_parquet(staging / "banking_products.parquet", index=False)

    cash = build(staging).set_index("month")["cash"]

    rates = fx.load_rates().query("currency == 'USD'").set_index("year")["per_eur"]
    assert cash.loc[M1] == pytest.approx(1200 / rates[2024])
    assert cash.loc["2026-08-01"] == pytest.approx(FINAL_BALANCE / rates[2026])

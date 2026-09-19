import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from xray.v2_fx import normalize_tables_eur


@pytest.fixture
def local_tables():
    return {
        "companies": pd.DataFrame({"company_id": ["c"], "currency": ["EUR"]}),
        "banking_products": pd.DataFrame(
            {"company_id": ["c"], "product_id": ["bank"], "currency": ["GBP"]}
        ),
        "debt_products": pd.DataFrame(
            {
                "company_id": ["c"],
                "product_id": ["loan"],
                "currency": ["EUR"],
                "outstanding": [-200.0],
                "granted": [500.0],
                "liquidity": [300.0],
            }
        ),
        "transactions": pd.DataFrame(
            {
                "company_id": ["c", "c"],
                "product_id": ["bank", "loan"],
                "date": pd.to_datetime(["2024-09-01", "2024-09-01"]),
                "amount": [86.9907, -100.0],
            }
        ),
        "invoices": pd.DataFrame(
            {
                "company_id": ["c"],
                "currency": ["GBP"],
                "issuance_date": pd.to_datetime(["2024-09-01"]),
                "amount": [86.9907],
                "pending_amount": [43.49535],
            }
        ),
        "balances": pd.DataFrame(
            {
                "product_id": ["bank"],
                "date": pd.to_datetime(["2026-09-01"]),
                "balance": [85.6611],
            }
        ),
    }


def test_previous_year_rates_use_product_units_and_preserve_input(local_tables):
    before = {name: frame.copy(deep=True) for name, frame in local_tables.items()}
    converted, metadata = normalize_tables_eur(local_tables)
    assert converted["transactions"].amount.tolist() == pytest.approx([100.0, -100.0])
    assert converted["transactions"].fx_rate_year.tolist() == [2023, 2023]
    assert converted["invoices"].pending_amount.iloc[0] == pytest.approx(50.0)
    assert converted["balances"].balance.iloc[0] == pytest.approx(100.0)
    assert converted["debt_products"].outstanding.iloc[0] == -200.0
    assert converted["transactions"].amount_local.tolist() == [86.9907, -100.0]
    assert metadata["by_company"]["c"]["fx_estimated"] is True
    assert metadata["coverage"]["rows_excluded"] == 0
    for name in local_tables:
        assert_frame_equal(local_tables[name], before[name])


@pytest.mark.parametrize("currency", ["XYZ", "MAD", "ARS", None])
def test_unsupported_and_untrusted_rates_never_become_parity(local_tables, currency):
    local_tables["banking_products"]["currency"] = currency
    local_tables["companies"]["currency"] = currency
    converted, metadata = normalize_tables_eur(local_tables)
    assert pd.isna(converted["transactions"].amount.iloc[0])
    assert pd.isna(converted["balances"].balance.iloc[0])
    assert converted["companies"].currency.iloc[0] == "EUR"
    assert metadata["by_company"]["c"]["partial"] is True
    assert metadata["by_company"]["c"]["native_currency_supported"] is False
    assert (currency or "UNKNOWN") in metadata["missing_currencies"]
    assert metadata["coverage"]["rows_excluded"] == 3


def test_debt_stocks_convert_at_snapshot_and_reject_second_conversion(local_tables):
    local_tables["debt_products"]["currency"] = "GBP"
    converted, _ = normalize_tables_eur(local_tables)
    assert converted["debt_products"].granted.iloc[0] == pytest.approx(500 / 0.856611)
    assert converted["transactions"].amount.iloc[1] == pytest.approx(-100 / 0.869907)
    with pytest.raises(ValueError, match="expected local input"):
        normalize_tables_eur(converted)

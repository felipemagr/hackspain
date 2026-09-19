import json

import pandas as pd
import pytest

from xray.v2 import build_payload, invoice_panel, transaction_panel


@pytest.fixture
def tables():
    companies = pd.DataFrame(
        {"company_id": ["c1", "c2"], "group_id": ["g1", "g1"], "currency": ["EUR", "EUR"]}
    )
    banking = pd.DataFrame(
        {
            "product_id": ["a1", "a2"],
            "company_id": ["c1", "c2"],
            "currency": ["EUR", "EUR"],
            "type": ["checking", "checking"],
        }
    )
    tx = pd.DataFrame(
        {
            "company_id": ["c1"] * 5,
            "product_id": ["a1"] * 5,
            "date": pd.to_datetime(["2024-09-05"] * 5),
            "amount": [100, -20, -5, -10, -7],
            "category": ["collection", "salary", "interest_charge", "transfer", "uncategorized"],
        }
    )
    invoices = pd.DataFrame(
        {
            "company_id": ["c1", "c2", "c1"],
            "currency": ["EUR"] * 3,
            "document_type": ["invoice"] * 3,
            "amount": [100, 300, -40],
            "side": ["receivable", "receivable", "payable"],
            "issuance_date": pd.to_datetime(["2024-09-01"] * 3),
            "due_date": pd.to_datetime(["2024-09-15", "2024-10-15", None]),
            "payment_date": pd.to_datetime(["2024-11-01", None, None]),
            "status": ["paid", "pending", "pending"],
        }
    )
    return {
        "companies": companies,
        "banking_products": banking,
        "transactions": tx,
        "invoices": invoices,
        "balances": pd.DataFrame(
            {"product_id": ["a1"], "date": pd.to_datetime(["2026-09-01"]), "balance": [50]}
        ),
        "debt_products": pd.DataFrame(
            columns=["product_id", "company_id", "currency", "outstanding"]
        ),
    }


def test_outflow_components_reconcile_and_interest_is_not_double_counted(tables):
    p = transaction_panel(tables["transactions"], tables["banking_products"], tables["companies"])
    r = p.iloc[0]
    assert r.outflow == 32
    assert r.total_outflow == 42
    assert (
        r.payroll + r.debt_service + r.fees + r.suppliers + r.tax + r.uncategorized + r.other
        == r.outflow
    )
    assert r.interest == r.debt_service == 5


def test_invoice_aging_payment_cutoff_and_side_coverage(tables):
    p = invoice_panel(tables["invoices"], tables["companies"])
    assert p.loc[("c1", "2024-09-01"), "rec_d1_30"] == 100
    assert p.loc[("c1", "2024-11-01"), "rec_open"] == 0
    assert p.loc[("c1", "2024-09-01"), "pay_unknown_due"] == 40
    assert p.loc[("c2", "2024-09-01"), "pay_companies"] == 0


def test_group_aggregates_amounts_before_ratios_and_missing_is_not_zero(tables):
    payload = build_payload(tables)
    group = payload["entities"]["g1"]
    r = group["monthly"][0]
    assert r["rec_open"] == 400
    assert r["rec_overdue_share"] == 0.25
    assert r["dso"] is None
    assert payload["entities"]["c2"]["monthly"][0]["pay_open"] is None
    assert group["debt_snapshot"]["owed"] is None
    assert all(m["cash"] is None for m in group["monthly"][:-1])
    assert group["monthly"][-1]["cash"] == 50
    assert group["monthly"][1]["inflow"] is None
    json.dumps(payload, allow_nan=False)


def test_currency_mismatch_excludes_rows_and_mixed_group_blocks_money(tables):
    tables["companies"].loc[1, "currency"] = "USD"
    tables["banking_products"].loc[0, "currency"] = "USD"
    payload = build_payload(tables)
    assert payload["entities"]["c1"]["monthly"][0]["excluded_tx_count"] == 5
    assert payload["entities"]["g1"]["currency_mixed"]
    assert payload["entities"]["g1"]["monthly"][0]["rec_open"] is None
    assert payload["entities"]["g1"]["monthly"][-1]["cash"] is None


def test_paid_without_payment_date_is_not_an_everlasting_open_invoice(tables):
    tables["invoices"].loc[0, "payment_date"] = pd.NaT
    p = invoice_panel(tables["invoices"], tables["companies"])
    assert p.loc[("c1", "2024-09-01"), "rec_open"] == 0
    assert p.loc[("c1", "2024-09-01"), "rec_companies"] == 0


def test_later_invoice_and_payment_do_not_change_earlier_months(tables):
    before = invoice_panel(tables["invoices"], tables["companies"])
    tables["invoices"].loc[0, "payment_date"] = pd.Timestamp("2024-12-15")
    future = tables["invoices"].iloc[[0]].copy()
    future["issuance_date"] = pd.Timestamp("2025-01-01")
    future["payment_date"] = pd.NaT
    future["status"] = "pending"
    tables["invoices"] = pd.concat([tables["invoices"], future], ignore_index=True)
    after = invoice_panel(tables["invoices"], tables["companies"])
    mask = before.index.get_level_values("month") < "2024-11-01"
    pd.testing.assert_frame_equal(before.loc[mask], after.loc[mask])


def test_scoring_uses_exact_invoice_age_and_group_amount_mass(tables):
    payload = build_payload(tables)
    company = payload["entities"]["c1"]["monthly"][0]
    group = payload["entities"]["g1"]["monthly"][0]
    assert company["rec_score_mass"] == 100 * 87.5
    assert company["pay_known_due_open"] == 0
    assert company["scoring"]["subscores"]["payables"]["score"] is None
    assert group["flow_companies"] == 1
    assert group["rec_known_due_open"] == 400
    assert group["scoring"]["subscores"]["receivables"]["score"] == (8750 + 30000) / 400
    assert group["scoring"]["subscores"]["liquidity"]["score"] is None
    assert payload["score_config"]["version"]


def test_guarantees_are_separate_from_drawn_debt(tables):
    tables["debt_products"] = pd.DataFrame(
        {
            "product_id": ["d1", "d2"],
            "company_id": ["c1", "c1"],
            "currency": ["EUR", "EUR"],
            "outstanding": [-450, -100],
            "type": ["guarantee", "loan"],
        }
    )
    snapshot = build_payload(tables)["entities"]["c1"]["debt_snapshot"]
    assert snapshot["owed"] == 100
    assert snapshot["guarantees"] == 450
    assert snapshot["guarantee_product_count"] == 1

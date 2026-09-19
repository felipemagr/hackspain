import pandas as pd
import pytest

from xray.pipeline import synth
from xray.pipeline.clean import build_from
from xray.pipeline.data import load_all
from xray.scoring.submit import predict

# The brief's worked example plus one quiet group, so the test stays under a few seconds.
ROSTER = [
    ("Glovo", "Delivery", 1_100e6, 2, "bending", True),
    ("Cabify", "Mobility", 750e6, 2, "improving", True),
    ("Idealista", "Real estate portal", 380e6, 1, "healthy", False),
]


@pytest.fixture(scope="module")
def dump(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    for name, table in synth.build(roster=ROSTER).items():
        table.to_csv(out / f"{name}.csv", index=False)
    return out


class TestDump:
    def test_has_the_nine_tables_and_cleans_like_the_challenge_dump(self, dump):
        raw = load_all(dump)
        assert set(raw) == {
            "groups",
            "companies",
            "banking_products",
            "debt_products",
            "debt_schedule_config",
            "transactions",
            "invoices",
            "balances",
        }
        cleaned = build_from(raw)
        assert len(cleaned["transactions"]) == len(raw["transactions"])
        assert set(cleaned["invoices"]["side"]) == {"receivable", "payable"}

    def test_snapshot_is_where_the_movements_leave_the_account(self, dump):
        raw = load_all(dump)
        flows = raw["transactions"].groupby("product_id")["amount"].sum()
        final = raw["balances"].set_index("product_id")["balance"]
        opening = final - flows.reindex(final.index).fillna(0)
        # Checking accounts open with a positive buffer; cards open at zero.
        kinds = raw["banking_products"].set_index("product_id")["type"]
        assert (opening[kinds == "checking"] > 0).all()
        assert opening[kinds == "card"].abs().max() < 0.01

    def test_unpaid_invoice_carries_the_source_placeholder(self, dump):
        inv = load_all(dump)["invoices"]
        unpaid = inv[inv["status"] != "paid"]
        assert len(unpaid) > 0
        assert (unpaid["payment_date"] == unpaid["due_date"]).all()
        assert (unpaid["pending_amount"] == unpaid["amount"]).all()


class TestStoriesEmerge:
    """The archetypes are written into the trail only; the score has to find them."""

    def test_bending_falls_and_improving_rises(self, dump):
        groups = predict(dump)["groups"]
        level = groups.pivot(index="month", columns="group_id", values="level")
        first, last = level.iloc[3], level.iloc[-1]
        assert last["GLOVO"] < first["GLOVO"] - 8
        assert last["CABIFY"] > first["CABIFY"] + 12
        assert abs(last["IDEALISTA"] - first["IDEALISTA"]) < 8

    def test_bending_group_is_alarmed_while_still_looking_fine(self, dump):
        groups = predict(dump)["groups"]
        glovo = groups[groups["group_id"] == "GLOVO"].set_index("month")
        first_alarm = glovo.index[glovo["state"].isin(["bending", "falling"])].min()
        assert pd.notna(first_alarm)
        assert glovo.loc[first_alarm, "tier"] in ("healthy", "coping")
        assert glovo.loc[first_alarm, "level"] > glovo["level"].iloc[-1]

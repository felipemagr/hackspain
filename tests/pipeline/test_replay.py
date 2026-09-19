import json

import pandas as pd
import pytest

from xray.pipeline import replay
from xray.pipeline.data import load_all
from xray.scoring.serve import publish
from xray.scoring.submit import predict

MONTHS = pd.date_range("2024-09-01", periods=12, freq="MS")


@pytest.fixture
def dump(tmp_path, write_dump):
    """Three groups, a year of flows, in the challenge's nine-CSV shape."""
    return write_dump(tmp_path / "raw", {"g1": ["c1", "c2"], "g2": ["c3"], "g3": ["c4"]}, seed=3)


class TestExtracts:
    def test_month_carries_its_transactions_and_a_balance_as_of_that_month(self, dump):
        raw = load_all(dump)
        first, later = replay.extracts(raw, MONTHS[0]), replay.extracts(raw, MONTHS[5])
        static = set(replay.STATIC_TABLES)
        assert static <= set(first) and not static & set(later)
        assert (later["transactions"]["date"].dt.to_period("M") == MONTHS[5].to_period("M")).all()
        # The snapshot for June is the final balance minus every booked flow after June.
        tx = raw["transactions"]
        after = tx[tx["date"] >= MONTHS[6]].groupby("product_id")["amount"].sum()
        final = raw["balances"].set_index("product_id")["balance"]
        expected = (final - after.reindex(final.index).fillna(0)).round(2)
        got = later["balances"].set_index("product_id")["balance"].round(2)
        pd.testing.assert_series_equal(got.sort_index(), expected.sort_index(), check_names=False)

    def test_invoice_lands_pending_then_paid_under_the_same_id(self, dump):
        raw = load_all(dump)
        inv = raw["invoices"]
        # First invoice of every company: issued 2025-01-05, paid 2025-02-20.
        january, february = (
            replay.extracts(raw, pd.Timestamp("2025-01-01")),
            replay.extracts(raw, pd.Timestamp("2025-02-01")),
        )
        ids = set(inv.loc[inv["issuance_date"] == "2025-01-05", "operation_id"])
        jan = january["invoices"].set_index("operation_id").loc[sorted(ids)]
        feb = february["invoices"].set_index("operation_id").loc[sorted(ids)]
        assert (jan["status"] == "pending").all() and jan["payment_date"].isna().all()
        assert (feb["status"] == "paid").all() and (feb["payment_date"] == "2025-02-20").all()


class TestReplayMatchesTheFullRun:
    def test_every_month_scores_as_it_does_in_the_full_run(self, dump, tmp_path):
        raw = load_all(dump)
        lake = tmp_path / "lake"
        full = predict(dump)["groups"].set_index(["group_id", "month"])["level"]
        for month in MONTHS:
            replay.land_month(raw, month, lake)
            tables = replay.rebuild(replay.month_end(month), lake)
            now = tables["scores"].set_index(["group_id", "month"])["level"].sort_index()
            expected = full.loc[full.index.get_level_values("month") <= month].sort_index()
            pd.testing.assert_series_equal(now, expected, check_names=False, atol=0.011)

    def test_publish_swaps_tables_and_stamps_a_version(self, dump, tmp_path):
        raw = load_all(dump)
        lake, serving = tmp_path / "lake", tmp_path / "serving"
        serving.mkdir()
        for month in MONTHS[:7]:
            replay.land_month(raw, month, lake)
        version = publish(replay.rebuild(replay.month_end(MONTHS[6]), lake), serving, "2025-03-31")
        assert json.loads((serving / "_version.json").read_text()) == version
        assert version["as_of"] == "2025-03-31" and version["latest_month"] == "2025-03-01"
        written = {p.stem for p in serving.glob("*.parquet")}
        assert written == set(version["tables"])
        assert not (serving / ".next").exists()

import pandas as pd
import pytest

from xray.pipeline import onboard, synth

ROSTER = [
    ("Glovo", "Delivery", 1_100e6, 1, "bending", True),
    ("Cabify", "Mobility", 750e6, 1, "improving", True),
    ("Idealista", "Real estate portal", 380e6, 1, "healthy", False),
    ("Wallapop", "Marketplace", 85e6, 1, "improving", True),
]


@pytest.fixture(scope="module")
def arriving(tmp_path_factory):
    out = tmp_path_factory.mktemp("arriving")
    for name, table in synth.build(roster=ROSTER).items():
        table.to_csv(out / f"{name}.csv", index=False)
    return out


@pytest.fixture
def base(tmp_path, write_dump):
    """A portfolio the pipeline already built: two plain groups under marts/ and processed/."""
    tables = onboard.panels_for(
        write_dump(tmp_path / "base_raw", {"g1": ["c1", "c2"], "g2": ["c3"]})
    )
    marts, processed = tmp_path / "marts", tmp_path / "processed"
    marts.mkdir()
    processed.mkdir()
    tables["panel_group"].to_parquet(marts / "panel_group.parquet", index=False)
    tables["panel_company"].to_parquet(marts / "panel_company.parquet", index=False)
    tables["companies"].to_parquet(processed / "companies.parquet", index=False)
    tables["groups"].to_parquet(processed / "groups.parquet", index=False)
    return marts, processed


class TestBatches:
    def test_dealt_round_robin_so_each_arrival_is_a_mix(self):
        assert onboard.batches(list("abcde"), 2) == [["a", "c", "e"], ["b", "d"]]

    def test_never_more_batches_than_groups(self):
        assert onboard.batches(["a", "b"], 5) == [["a"], ["b"]]


class TestRun:
    def test_arrivals_join_the_portfolio_and_nobody_leaves(self, arriving, base, tmp_path):
        marts, processed = base
        serving = tmp_path / "serving"
        serving.mkdir()
        versions = onboard.run(
            arriving,
            n_batches=2,
            gap=0,
            marts_dir=marts,
            processed_dir=processed,
            serving_dir=serving,
        )
        # Today's portfolio goes live first, whatever the serving directory held before.
        assert [v["n_groups"] for v in versions] == [2, 4, 6]
        groups = pd.read_parquet(serving / "groups.parquet").set_index("group_id")
        assert set(groups.index) == {"g1", "g2", "GLOVO", "CABIFY", "IDEALISTA", "WALLAPOP"}
        # The plain groups keep their id as name; the newcomers bring theirs.
        assert groups.loc["g1", "name"] == "g1" and groups.loc["GLOVO", "name"] == "Glovo"

    def test_starts_from_nothing_when_the_pipeline_never_ran(self, arriving, tmp_path):
        serving = tmp_path / "serving"
        serving.mkdir()
        versions = onboard.run(
            arriving,
            n_batches=1,
            gap=0,
            marts_dir=tmp_path / "no_marts",
            processed_dir=tmp_path / "no_processed",
            serving_dir=serving,
        )
        assert [v["n_groups"] for v in versions] == [4]

    def test_summary_names_the_newcomers_worst_first(self, arriving, tmp_path):
        serving = tmp_path / "serving"
        serving.mkdir()
        onboard.run(
            arriving,
            n_batches=1,
            gap=0,
            marts_dir=tmp_path / "x",
            processed_dir=tmp_path / "y",
            serving_dir=serving,
        )
        tables = {
            "groups": pd.read_parquet(serving / "groups.parquet"),
            "scores": pd.read_parquet(serving / "scores.parquet"),
        }
        text = onboard.summary(tables, ["GLOVO", "CABIFY"])
        assert text.startswith("2 companies connected. Glovo:")
        assert "Cabify:" in text and "improving" in text

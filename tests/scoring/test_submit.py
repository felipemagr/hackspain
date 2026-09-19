import pandas as pd
import pytest

from xray.scoring.submit import predict

MONTHS = pd.date_range("2024-09-01", periods=12, freq="MS")


@pytest.fixture
def dumps(tmp_path, write_dump):
    """The same three groups as one dump, and the first group on its own."""
    plan = {"g1": ["c1", "c2"], "g2": ["c3"], "g3": ["c4"]}
    write_dump(tmp_path / "all", plan)
    write_dump(tmp_path / "alone", {"g1": plan["g1"]})
    return tmp_path / "all", tmp_path / "alone"


class TestPredict:
    def test_one_row_per_group_month_and_per_company_month(self, dumps):
        out = predict(dumps[0])
        assert set(out["groups"]["group_id"]) == {"g1", "g2", "g3"}
        assert out["groups"].groupby("group_id").size().eq(len(MONTHS)).all()
        assert set(out["companies"]["company_id"]) == {"c1", "c2", "c3", "c4"}
        assert out["groups"]["level"].between(0, 100).all()

    def test_a_group_scores_the_same_alone_as_in_a_portfolio(self, dumps):
        """Nothing is fitted, so the hidden test cannot move a group's score."""
        together = predict(dumps[0])["groups"].query("group_id == 'g1'").reset_index(drop=True)
        alone = predict(dumps[1])["groups"].reset_index(drop=True)
        pd.testing.assert_frame_equal(together, alone)

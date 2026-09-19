import pandas as pd
import pytest

from xray.pipeline.data import load_all, load_table


@pytest.fixture
def data_dir(tmp_path):
    """Data dir with a single tiny invoices table."""
    (tmp_path / "invoices.csv").write_text(
        "company_id,issue_date,amount\nc1,2025-01-05,1000.0\nc1,not-a-date,500.0\n"
    )
    return tmp_path


class TestLoadTable:
    def test_parses_date_columns(self, data_dir):
        df = load_table("invoices", data_dir)

        assert pd.api.types.is_datetime64_any_dtype(df["issue_date"])
        assert df["issue_date"].isna().sum() == 1

    def test_missing_table_raises(self, data_dir):
        with pytest.raises(FileNotFoundError):
            load_table("transactions", data_dir)


def test_load_all_skips_missing_tables(data_dir):
    assert list(load_all(data_dir)) == ["invoices"]

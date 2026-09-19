import json

import pandas as pd
from fastapi.testclient import TestClient

from xray.api.main import app
from xray.settings import get_settings


def _serving(tmp_path, monkeypatch):
    pd.DataFrame(
        {
            "group_id": ["g1", "g2"],
            "month": pd.to_datetime(["2026-08-01", "2026-08-01"]),
            "level": [70.0, float("nan")],
        }
    ).to_parquet(tmp_path / "scores.parquet")
    monkeypatch.setenv("XRAY_SERVING_DIR", str(tmp_path))
    get_settings.cache_clear()
    return tmp_path


class TestTables:
    def test_returns_every_row_with_null_for_nan(self, tmp_path, monkeypatch):
        _serving(tmp_path, monkeypatch)
        with TestClient(app) as client:
            rows = client.get("/api/v1/tables/scores").json()
        assert [r["group_id"] for r in rows] == ["g1", "g2"]
        assert rows[0]["level"] == 70.0 and rows[1]["level"] is None
        assert rows[0]["month"].startswith("2026-08-01")

    def test_unknown_table_is_404(self, tmp_path, monkeypatch):
        _serving(tmp_path, monkeypatch)
        with TestClient(app) as client:
            assert client.get("/api/v1/tables/nope").status_code == 404


class TestVersion:
    def test_reads_the_stamp_and_picks_up_new_files(self, tmp_path, monkeypatch):
        serving = _serving(tmp_path, monkeypatch)
        with TestClient(app) as client:
            first = client.get("/api/v1/version").json()
            assert first["tables"] == ["scores"]
            # A publish lands while the API is up: a new table and a version stamp.
            pd.DataFrame({"group_id": ["g1"]}).to_parquet(serving / "offers.parquet")
            (serving / "_version.json").write_text(
                json.dumps({"build_id": "b2", "built_at": "now", "latest_month": "2026-08-01"})
            )
            second = client.get("/api/v1/version").json()
            assert second["build_id"] == "b2"
            assert second["tables"] == ["offers", "scores"]
            assert client.get("/api/v1/tables/offers").status_code == 200

    def test_without_a_stamp_the_id_comes_from_the_files(self, tmp_path, monkeypatch):
        _serving(tmp_path, monkeypatch)
        with TestClient(app) as client:
            body = client.get("/api/v1/version").json()
        assert body["build_id"] and body["tables"] == ["scores"]

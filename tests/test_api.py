import pandas as pd
from fastapi.testclient import TestClient

from xray.api.main import app
from xray.settings import get_settings


def test_health_lists_serving_tables(tmp_path, monkeypatch):
    pd.DataFrame({"group_id": ["g1"], "score": [70.0]}).to_parquet(tmp_path / "scores.parquet")
    monkeypatch.setenv("XRAY_SERVING_DIR", str(tmp_path))
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["tables"] == ["scores"]

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from xray.api.main import app
from xray.settings import get_settings

ROWS = [
    ("g1", "2026-05-01", "shift", "down", 12.0),
    ("g1", "2026-06-01", "jump", "up", 30.0),
    ("g2", "2026-06-01", "shift", "up", 4.0),
]


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """An API serving three invented alerts and nothing else."""
    pd.DataFrame(
        {
            "group_id": [r[0] for r in ROWS],
            "month": pd.to_datetime([r[1] for r in ROWS]),
            "kind": [r[2] for r in ROWS],
            "direction": [r[3] for r in ROWS],
            "state_from": "healthy",
            "state_to": "bending",
            "onset_month": pd.Timestamp("2026-01-01"),
            "level_at_onset": 82.0,
            "level_at_alert": 68.4,
            "delta_level": -13.6,
            "trend": -2.1,
            "compound": 60.0,
            "tier": "coping",
            "driver_1": "liquidity",
            "driver_2": None,
            "sigmas": None,
            "resolution": "",
            "severity": [r[4] for r in ROWS],
            "anticipation_months": None,
            "late": False,
        }
    ).to_parquet(tmp_path / "alerts.parquet", index=False)
    monkeypatch.setenv("XRAY_SERVING_DIR", str(tmp_path))
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client


def test_feed_is_worst_first_within_the_latest_month(client):
    body = client.get("/api/v1/alerts").json()

    assert body["total"] == 3
    assert [a["group_id"] for a in body["data"]] == ["g1", "g2", "g1"]
    assert body["data"][0]["severity"] == 30.0


def test_filters_narrow_the_feed(client):
    down = client.get("/api/v1/alerts", params={"direction": "down"}).json()
    june = client.get("/api/v1/alerts", params={"since": "2026-06-01"}).json()

    assert down["total"] == 1
    assert june["total"] == 2


def test_one_group_reads_its_own_history_oldest_first(client):
    body = client.get("/api/v1/groups/g1/alerts").json()

    assert [a["month"] for a in body] == ["2026-05-01", "2026-06-01"]


def test_a_group_that_never_moved_returns_an_empty_list(client):
    assert client.get("/api/v1/groups/nobody/alerts").json() == []

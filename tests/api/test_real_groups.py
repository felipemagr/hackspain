from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

import xray.api.main as api_main
from xray.settings import get_settings


def test_viewer_shows_empty_state_without_real_scores(tmp_path, monkeypatch):
    monkeypatch.setenv("XRAY_SERVING_DIR", str(tmp_path))
    monkeypatch.setattr(api_main, "MARTS_DIR", tmp_path)
    get_settings.cache_clear()

    with TestClient(api_main.app) as client:
        page = client.get("/viewer")
        listing = client.get("/api/v1/real-groups")
        detail = client.get("/api/v1/real-groups/GROUP_0001")

    assert page.status_code == 200
    assert "Explorador de scores" in page.text
    assert listing.json() == {"data": [], "total": 0, "offset": 0, "limit": 250, "available": False}
    assert detail.status_code == 503


def test_real_group_endpoints_read_marts_and_preserve_missing(tmp_path: Path, monkeypatch):
    pd.DataFrame(
        {
            "group_id": ["GROUP_0001", "GROUP_0001", "GROUP_0002"],
            "month": pd.to_datetime(["2026-07-01", "2026-08-01", "2026-08-01"]),
            "liquidity": [None, 62.0, None],
            "cash_generation": [None, 70.0, None],
            "payment_discipline": [None, 80.0, None],
            "collections": [None, 55.0, None],
            "debt_burden": [None, 60.0, None],
            "level": [None, 65.0, None],
            "level_uncapped": [None, 65.0, None],
            "is_capped": [False, False, False],
            "coverage": [0.0, 1.0, 0.0],
            "uncategorized_share": [None, 0.3, None],
            "currency_mixed": [False, False, True],
            "trend": [None, 1.6, None],
            "compound": [None, 71.4, None],
            "state": ["not_enough_data", "improving", "not_enough_data"],
            "tier": [None, "coping", None],
            "months_observed": [1.0, 2.0, 1.0],
            "buffer_days": [None, 35.0, None],
            "operating_margin": [None, 0.12, None],
            "ap_days_beyond_terms": [None, 4.0, None],
            "ar_days_beyond_terms": [None, 8.0, None],
            "known_inflow_3m": [None, 1000.0, None],
        }
    ).to_parquet(tmp_path / "real_scores.parquet")
    pd.DataFrame(
        {
            "group_id": ["GROUP_0001"],
            "month": pd.to_datetime(["2026-08-01"]),
            "pillar": ["liquidity"],
            "score": [62.0],
            "contribution": [3.0],
            "delta_score": [None],
            "delta_contribution": [None],
        }
    ).to_parquet(tmp_path / "real_drivers.parquet")
    monkeypatch.setenv("XRAY_SERVING_DIR", str(tmp_path / "serving"))
    monkeypatch.setattr(api_main, "MARTS_DIR", tmp_path)
    get_settings.cache_clear()

    with TestClient(api_main.app) as client:
        listing = client.get("/api/v1/real-groups")
        detail = client.get("/api/v1/real-groups/GROUP_0001")
        absent = client.get("/api/v1/real-groups/NO_SUCH_GROUP")

    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert listing.json()["data"][0]["level"] == 65.0
    assert listing.json()["data"][1]["level"] is None
    assert detail.status_code == 200
    assert detail.json()["scores"][0]["level"] is None
    assert detail.json()["drivers"][0]["pillar"] == "liquidity"
    assert absent.status_code == 404

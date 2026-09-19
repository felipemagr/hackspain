"""The local serving API remains isolated from legacy score marts."""

import json

from fastapi.testclient import TestClient

from xray.api.main import app
from xray.scoring.local_serving import export_payload
from xray.settings import get_settings
from xray.v2_scores import load_score_config, score_entity


def test_local_endpoints_and_no_legacy_fallback(tmp_path, monkeypatch):
    entities = {}
    for entity_id, kind in (("EXAMPLE_C", "company"), ("EXAMPLE_G", "group")):
        entity = {
            "id": entity_id,
            "kind": kind,
            "group_id": "EXAMPLE_G",
            "name": "Example Corp",
            "currency": "EUR",
            "members": ["EXAMPLE_C"],
            "monthly": [
                {
                    "month": f"2025-{month:02d}",
                    "inflow": 120,
                    "outflow": 140,
                    "debt_service": 60,
                    "flow_companies": 1,
                    "total_companies": 1,
                }
                for month in range(1, 7)
            ],
        }
        for record, scoring in zip(entity["monthly"], score_entity(entity), strict=True):
            record["scoring"] = scoring
        entities[entity_id] = entity
    export_payload(
        {"entities": entities, "score_config": load_score_config()}, tmp_path, {"source": "test"}
    )
    monkeypatch.setenv("XRAY_SERVING_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert app.state.real_tables == set()
            assert client.get("/api/v1/scoring/config").json()["provenance"]["source"] == "test"
            listing = client.get("/api/v1/scoring/entities?kind=group&query=Example").json()
            assert listing["total"] == 1
            assert listing["data"][0]["id"] == "EXAMPLE_G"
            url = "/api/v1/scoring/entities/EXAMPLE_C"
            before = client.get(url).json()
            response = client.post(
                url + "/evaluate",
                json={"weights": {"financial": {"generation": 1, "debt_coverage": 0}}},
            )
            assert response.status_code == 200
            assert response.json()["monthly"][-1]["scoring"]["level"]["score"] == 100
            assert client.get(url).json() == before
            assert (
                client.post(url + "/evaluate", json={"weights": {"invalid": {}}}).status_code == 422
            )
            assert client.get("/api/v1/scoring/entities/missing").status_code == 404
            portfolio = client.get(
                "/api/v1/scoring/portfolio?kind=company", headers={"Accept-Encoding": "gzip"}
            )
            assert portfolio.headers["content-encoding"] == "gzip"
            assert len(portfolio.json()["observations"]) == 6
            chat = client.post(
                "/api/v1/chats",
                json={"entity_id": "missing", "message": "Explain"},
                headers={"Accept-Encoding": "gzip"},
            )
            assert chat.headers["content-type"].startswith("text/event-stream")
            assert "content-encoding" not in chat.headers
            assert '"type": "done"' in chat.text
            assert before["monthly"][0]["scoring"]["level"]["score"] is None
            profile = json.loads((tmp_path / "score_profile.json").read_text())
            assert profile["config"]["weights"] == before["config"]["weights"]
    finally:
        get_settings.cache_clear()


def test_missing_local_export_has_no_legacy_scoring_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("XRAY_SERVING_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/scoring/config").status_code == 503
            assert client.get("/api/v1/scoring/entities").status_code == 503
    finally:
        get_settings.cache_clear()

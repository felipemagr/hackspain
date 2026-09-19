import pytest
from fastapi.testclient import TestClient

from xray.api.main import app
from xray.api.routers import alert_rules
from xray.settings import Settings


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """An API with an empty rule book in a scratch folder and no model behind the parser."""
    settings = Settings(_env_file=None, serving_dir=tmp_path, helmcode_api_key=None)
    monkeypatch.setattr(alert_rules, "get_settings", lambda: settings)
    with TestClient(app) as test_client:
        yield test_client


def test_a_plain_request_is_saved_listed_and_dropped(client):
    created = client.post(
        "/api/v1/alert-rules",
        json={"text": "slack me when this group starts falling", "group_id": "GROUP_0220"},
    )

    assert created.status_code == 201
    (rule,) = created.json()
    assert (rule["id"], rule["channel"], rule["min_urgency"]) == (1, "slack", "critical")
    assert rule["groups"] == ["GROUP_0220"]
    assert [r["id"] for r in client.get("/api/v1/alert-rules").json()] == [1]
    assert client.delete("/api/v1/alert-rules/1").status_code == 204
    assert client.delete("/api/v1/alert-rules/1").status_code == 404
    assert client.get("/api/v1/alert-rules").json() == []


def test_a_request_without_a_channel_is_rejected(client):
    response = client.post("/api/v1/alert-rules", json={"text": "tell me when it falls"})

    assert response.status_code == 422
    assert "slack or email" in response.json()["detail"]

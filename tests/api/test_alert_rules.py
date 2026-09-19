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


def test_the_test_button_sends_the_rule_down_its_channel(client, monkeypatch):
    sent = []
    monkeypatch.setattr(alert_rules, "send_slack", lambda text: sent.append(text) or True)
    client.post("/api/v1/alert-rules", json={"text": "slack me when GROUP_0220 falls"})

    assert client.post("/api/v1/alert-rules/1/test").status_code == 204
    assert "Slack gets critical alerts on GROUP_0220" in sent[0]
    assert client.post("/api/v1/alert-rules/9/test").status_code == 404


def test_the_test_button_says_when_the_channel_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(alert_rules, "send_slack", lambda text: False)
    client.post("/api/v1/alert-rules", json={"text": "slack me everything"})

    response = client.post("/api/v1/alert-rules/1/test")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]

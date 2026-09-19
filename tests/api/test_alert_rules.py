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


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        (
            "tell me when it falls",
            "Not saved: critical alerts on any group. Slack or email? For email, say the "
            "address too.",
        ),
        (
            "email me when it falls",
            "Not saved: critical alerts on any group. Which email address?",
        ),
    ],
)
def test_a_request_missing_the_channel_or_the_address_is_rejected_with_the_question(
    client, text, detail
):
    response = client.post("/api/v1/alert-rules", json={"text": text})

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert client.get("/api/v1/alert-rules").json() == []


def test_a_score_line_and_an_address_become_a_level_rule_to_that_address(client):
    created = client.post(
        "/api/v1/alert-rules",
        json={"text": "alert me at cfo@example.com when GROUP_0130 goes above 80"},
    )

    (rule,) = created.json()
    assert (rule["channel"], rule["email_to"]) == ("email", "cfo@example.com")
    assert (rule["level_above"], rule["groups"]) == (80, ["GROUP_0130"])
    assert rule["min_severity"] is None


def test_a_rule_is_switched_off_reconfigured_and_left_alone_where_not_asked(client):
    client.post("/api/v1/alert-rules", json={"text": "slack me when GROUP_0220 falls"})

    off = client.patch("/api/v1/alert-rules/1", json={"enabled": False})
    assert off.status_code == 200
    assert (off.json()["enabled"], off.json()["min_urgency"]) == (False, "critical")

    moved = client.patch(
        "/api/v1/alert-rules/1",
        json={"channel": "email", "email_to": "cfo@example.com", "level_below": 40, "groups": []},
    )
    rule = moved.json()
    assert (rule["channel"], rule["email_to"], rule["level_below"]) == (
        "email",
        "cfo@example.com",
        40,
    )
    assert (rule["groups"], rule["enabled"]) == ([], False)

    # Back to Slack drops the address with it.
    back = client.patch("/api/v1/alert-rules/1", json={"channel": "slack"}).json()
    assert (back["channel"], back["email_to"]) == ("slack", None)
    assert client.patch("/api/v1/alert-rules/9", json={"enabled": True}).status_code == 404


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
    assert response.json()["detail"].startswith("Slack is not configured on the server")

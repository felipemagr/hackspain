from fastapi.testclient import TestClient

from xray.api.main import app


def test_agents_lists_the_fleet_the_chat_can_dispatch():
    with TestClient(app) as client:
        response = client.get("/api/v1/agents")

    assert response.status_code == 200
    agents = {agent["id"]: agent for agent in response.json()["agents"]}
    assert list(agents) == ["scorecard", "ledger", "simulator", "peers", "macro", "market"]
    assert all(agent["rules"] and agent["tools"] for agent in agents.values())


def test_client_errors_land_in_the_api_log(caplog):
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/client-errors",
            json={"message": "x is null", "url": "/?group=G1", "stack": "at GroupDetail " * 900},
        )

    assert response.status_code == 204
    assert "client render error on /?group=G1: x is null" in caplog.text
    assert len(caplog.text) < 5000

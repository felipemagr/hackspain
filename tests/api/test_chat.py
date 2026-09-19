from fastapi.testclient import TestClient

from xray.api.main import app


def test_agents_lists_the_fleet_the_chat_can_dispatch():
    with TestClient(app) as client:
        response = client.get("/api/v1/agents")

    assert response.status_code == 200
    agents = {agent["id"]: agent for agent in response.json()["agents"]}
    assert list(agents) == [
        "diagnosis",
        "monitor",
        "working_capital",
        "customers",
        "investor",
        "market",
    ]
    assert all(agent["rules"] and agent["tools"] for agent in agents.values())

from fastapi.testclient import TestClient

from xray.api.main import app


def test_agents_lists_the_fleet_the_chat_can_dispatch():
    with TestClient(app) as client:
        response = client.get("/api/v1/agents")

    assert response.status_code == 200
    kinds = {agent["id"]: agent["kind"] for agent in response.json()["agents"]}
    assert kinds["score"] == "data"
    assert kinds["sector"] == "web"

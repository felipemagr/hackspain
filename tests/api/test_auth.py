from fastapi.testclient import TestClient

from xray.api import auth
from xray.api.main import app
from xray.settings import Settings


def test_with_a_key_configured_only_calls_carrying_it_pass(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, serving_dir=tmp_path, LIGHTHOUSE_API_KEY="s3cret")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    with TestClient(app) as client:
        assert client.get("/api/v1/version").status_code == 401
        assert client.get("/api/v1/scoring/config").status_code == 401
        assert (
            client.post(
                "/api/v1/view-chats", json={"entity_id": "EXAMPLE_G", "message": "Explain"}
            ).status_code
            == 401
        )
        assert client.get("/api/v1/version", headers={"X-API-Key": "nope"}).status_code == 401
        assert client.get("/api/v1/version", headers={"X-API-Key": "s3cret"}).status_code == 200
        assert client.get("/health").status_code == 200

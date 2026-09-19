"""The local chat preserves entity, date and score configuration boundaries."""

import json

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from xray.agents.local_scoring import evidence_for, run_local_chat
from xray.api.routers.chat import ChatRequest, router
from xray.scoring.local_serving import export_payload, read_entity, reweight_entity
from xray.settings import Settings
from xray.v2_scores import load_score_config, score_entity


@pytest.fixture
def local_db(tmp_path):
    config = load_score_config()
    entities = {}
    for entity_id, kind in (("COMP_EXAMPLE", "company"), ("GROUP_EXAMPLE", "group")):
        entity = {
            "id": entity_id,
            "kind": kind,
            "group_id": "GROUP_EXAMPLE",
            "currency": "EUR",
            "original_currency": ["USD"],
            "fx_estimated": True,
            "debt_snapshot": {"date": "2025-06-01", "owed": 500},
            "members": ["COMP_EXAMPLE"],
            "monthly": [
                {
                    "month": f"2025-{month:02d}",
                    "inflow": 120 + month,
                    "outflow": 100,
                    "total_inflow": 200 + month,
                    "total_outflow": 150,
                    "net": 20 + month,
                    "fx_estimated_tx_count": 1 if month > 3 else 0,
                    "debt_service": 60,
                    "total_companies": 1,
                    "flow_companies": 1,
                    "perimeter_changed": False,
                }
                for month in range(1, 7)
            ],
        }
        for row, scoring in zip(entity["monthly"], score_entity(entity), strict=True):
            row["scoring"] = scoring
        entities[entity_id] = entity
    export_payload({"entities": entities, "score_config": config}, tmp_path, {})
    with duckdb.connect() as db:
        for table in ("score_entities", "score_observations"):
            db.execute(
                f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?)",
                [str(tmp_path / f"{table}.parquet")],
            )
        yield db


@pytest.mark.parametrize("entity_id", ["COMP_EXAMPLE", "GROUP_EXAMPLE"])
def test_fallback_uses_selected_entity_latest_and_exact_weights(local_db, entity_id):
    weights = {"financial": {"generation": 0, "debt_coverage": 1}}
    body = ChatRequest(entity_id=entity_id, message="Explica", weights=weights)
    events = list(run_local_chat(body, local_db, Settings(helmcode_api_key="")))
    answer = next(event["text"] for event in events if event["type"] == "token")
    detail = reweight_entity(read_entity(local_db, entity_id, config=load_score_config()), weights)
    score = detail["monthly"][-1]["scoring"]["level"]["score"]
    assert f"{entity_id} · 2025-06" in answer
    assert f"nivel {score:.2f}" in answer
    assert "determinista" in answer
    assert events[-1]["type"] == "done"
    planned = next(event for event in events if event["type"] == "plan")["agents"][0]
    assert planned["target"] == entity_id
    assert all(
        event["run"] == planned["run"] for event in events if event["type"] in {"agent", "step"}
    )


def test_llm_tools_cannot_read_future_or_other_entities(local_db, monkeypatch):
    calls = []

    class Provider:
        def __init__(self, **kwargs):
            pass

        def complete(self, system, user):
            calls.append(json.loads(user))
            return (
                '{"tools":["history","cash","erp","debt","members"]}'
                if len(calls) == 1
                else "Respuesta comprobada"
            )

    monkeypatch.setattr("xray.agents.llm.OpenAICompatibleLLM", Provider)
    body = ChatRequest(entity_id="COMP_EXAMPLE", month="2025-03", message="Explica")
    events = list(run_local_chat(body, local_db, Settings(helmcode_api_key="fake")))
    evidence = calls[-1]["evidence"]
    assert evidence["entity"]["id"] == "COMP_EXAMPLE"
    assert [r["month"] for r in evidence["history"]] == ["2025-01", "2025-02", "2025-03"]
    assert "2025-04" not in json.dumps(calls)
    assert evidence["cash"]["observations"][-1]["total_inflow"] == 203
    assert evidence["cash"]["observations"][-1]["total_outflow"] == 150
    assert evidence["cash"]["observations"][-1]["net"] == 23
    assert evidence["fx"]["original_currency"] == ["USD"]
    assert evidence["fx"]["history_fx_estimated_tx_count"] == 0
    assert "snapshot" not in evidence["debt"]
    assert events[-2] == {"type": "token", "text": "Respuesta comprobada"}
    steps = [event for event in events if event["type"] == "step"]
    assert [step["n"] for step in steps] == [1, 2, 3, 4, 5]
    assert all(step["input"] == "COMP_EXAMPLE, hasta 2025-03" for step in steps)
    assert all(step["ms"] >= 0 for step in steps)
    assert next(event for event in events if event["type"] == "plan")["company"] is None


def test_debt_tool_includes_only_snapshot_retained_by_asof_read(local_db):
    detail = read_entity(local_db, "COMP_EXAMPLE", "2025-06", load_score_config())
    assert evidence_for(detail, "debt")["snapshot"]["owed"] == 500


def test_chat_route_selects_local_profile_and_unknown_entity(local_db):
    app = FastAPI()
    app.include_router(router)
    app.state.db = local_db
    app.state.tables = {"score_entities", "score_observations"}
    app.state.score_profile = {"config": load_score_config()}
    with TestClient(app) as client:
        response = client.post("/api/v1/chats", json={"entity_id": "absent", "message": "Explica"})
    assert response.status_code == 200
    assert '"type": "error"' in response.text
    assert '"type": "done"' in response.text

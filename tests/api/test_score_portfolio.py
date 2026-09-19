"""Compact portfolio history preserves stored scores and missing observations."""

import json

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient

from xray.api.routers.scoring import router


def test_portfolio_preserves_scope_metadata_nulls_and_exact_scores():
    app = FastAPI()
    app.include_router(router)
    app.state.tables = {"score_entities", "score_observations"}
    app.state.score_profile = {"config": {"version": "example"}}
    with duckdb.connect() as db:
        app.state.db = db
        db.execute(
            "CREATE TABLE score_entities (kind VARCHAR, entity_id VARCHAR, metadata_json JSON)"
        )
        db.execute(
            "CREATE TABLE score_observations (kind VARCHAR, entity_id VARCHAR, month VARCHAR, "
            "level DOUBLE, confidence DOUBLE, evolution DOUBLE, record_json JSON)"
        )
        metadata = {
            "id": "EXAMPLE_C",
            "kind": "company",
            "members": ["EXAMPLE_C"],
            "countries": ["ES"],
            "currency": "EUR",
            "fx_estimated": True,
        }
        db.execute(
            "INSERT INTO score_entities VALUES ('company', 'EXAMPLE_C', ?)", [json.dumps(metadata)]
        )
        db.execute("INSERT INTO score_entities VALUES ('group', 'EXAMPLE_G', '{}')")
        scoring = {
            "level": {"coverage": 0.75},
            "evolution": {"confidence": 50},
            "subscores": {"generation": {"score": 33.123456789, "reason": "large evidence"}},
            "families": {"financial": {"score": 41.25}},
        }
        for month, level in (("2025-01", None), ("2025-02", 42.123456789)):
            db.execute(
                "INSERT INTO score_observations VALUES ('company', 'EXAMPLE_C', ?, ?, 80, NULL, ?)",
                [month, level, json.dumps({"scoring": scoring, "inflow": 999})],
            )
        with TestClient(app) as client:
            response = client.get("/api/v1/scoring/portfolio?kind=company")
            assert response.status_code == 200
            body = response.json()
            assert body["entities"] == [metadata]
            assert body["config"] == {"version": "example"}
            first, last = body["observations"]
            assert first["month"] == "2025-01"
            assert first["level"] is None
            assert last["level"] == 42.123456789
            assert last["evolution"] is None
            assert last["confidence"] == 80
            assert last["evolution_confidence"] == 50
            assert last["coverage"] == 0.75
            assert last["subscores"]["generation"] == {"score": 33.123456789}
            assert last["subscores"]["liquidity"] == {"score": None}
            assert last["families"]["financial"] == {"score": 41.25}
            assert "inflow" not in last
            assert client.get("/api/v1/scoring/portfolio?kind=group").json()["observations"] == []
            assert client.get("/api/v1/scoring/portfolio?kind=invalid").status_code == 422


def test_portfolio_requires_local_export():
    app = FastAPI()
    app.include_router(router)
    app.state.tables = set()
    with TestClient(app) as client:
        assert client.get("/api/v1/scoring/portfolio").status_code == 503

"""Round-trip local observations and reversible scorecard evaluation."""

import duckdb
import pytest

from xray.scoring.local_serving import export_payload, read_entity, reweight_entity
from xray.v2_scores import load_score_config, score_entity


def sample_payload() -> dict:
    """Invented company and group with unavailable first-month evidence."""
    entities = {}
    for entity_id, kind in (("EXAMPLE_C", "company"), ("EXAMPLE_G", "group")):
        entity = {
            "id": entity_id,
            "kind": kind,
            "group_id": "EXAMPLE_G",
            "currency": "EUR",
            "members": ["EXAMPLE_C"],
            "name": "Example Corp",
            "debt_snapshot": {"date": "2026-09-01", "owed": 50},
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
        for row, score in zip(entity["monthly"], score_entity(entity), strict=True):
            row["scoring"] = score
        entities[entity_id] = entity
    return {"entities": entities, "score_config": load_score_config()}


def test_roundtrip_cutoff_nulls_and_reweight_isolation(tmp_path):
    payload = sample_payload()
    export_payload(payload, tmp_path, {"source": "test"})
    with duckdb.connect() as db:
        for name in ("score_entities", "score_observations"):
            db.execute(f"CREATE VIEW {name} AS SELECT * FROM '{tmp_path / (name + '.parquet')}'")
        detail = read_entity(db, "EXAMPLE_G", "2025-03", payload["score_config"])
        assert len(detail["monthly"]) == 3
        assert "debt_snapshot" not in detail["entity"]
        assert detail["members"][0]["id"] == "EXAMPLE_C"
        assert detail["monthly"][0]["scoring"]["level"]["score"] is None
        changed = reweight_entity(detail, {"financial": {"generation": 1, "debt_coverage": 0}})
        assert changed["monthly"][-1]["scoring"]["level"]["score"] == 100
        assert "level" not in changed["members"][0]
        assert "confidence" not in changed["members"][0]
        assert "level" in detail["members"][0]
        assert detail["monthly"][-1]["scoring"]["level"]["score"] < 100
        assert read_entity(db, "' OR 1=1 --") is None


@pytest.mark.parametrize(
    "weights",
    [
        {"unknown": {}},
        {"financial": {"unknown": 1}},
        {"financial": {"generation": -1}},
        {"financial": {"generation": float("nan")}},
        {"financial": {"generation": 0, "debt_coverage": 0}},
    ],
)
def test_invalid_weights_rejected(weights):
    with pytest.raises(ValueError):
        reweight_entity({"config": load_score_config()}, weights)

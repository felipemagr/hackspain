"""The view assistant reads evidence and returns bounded actions without rescoring."""

import json

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from xray.agents.llm import OpenAICompatibleLLM
from xray.agents.view import ChartConfig, ViewChatRequest, run_view_chat
from xray.api.routers.view_chat import router
from xray.settings import Settings, get_settings

WEIGHTS = {"financial": 0.4, "liquidity": 0.2, "receivables": 0.2, "payables": 0.2}
CONFIG = {"weights": {"level": WEIGHTS}}


@pytest.fixture
def evidence_db():
    with duckdb.connect() as db:
        db.execute("CREATE TABLE score_entities (entity_id VARCHAR, metadata_json JSON)")
        db.execute(
            "CREATE TABLE score_observations (entity_id VARCHAR, month VARCHAR, record_json JSON)"
        )
        metadata = {
            "id": "EXAMPLE_G",
            "kind": "group",
            "currency": "EUR",
            "members": [],
            "debt_snapshot": {"date": "2025-09-01", "outstanding": 999999},
        }
        db.execute("INSERT INTO score_entities VALUES (?, ?)", ["EXAMPLE_G", json.dumps(metadata)])
        for month, flow in (("2025-01", 100), ("2025-02", 200), ("2025-03", 777777)):
            record = {
                "month": month,
                "inflow": flow,
                "scoring": {
                    "level": {"score": 65},
                    "families": {
                        "financial": {"score": 80, "confidence": 50},
                        "liquidity": {"score": 20, "confidence": 100},
                        "receivables": {"score": None, "confidence": 0},
                        "payables": {"score": 80, "confidence": 100},
                    },
                },
            }
            db.execute(
                "INSERT INTO score_observations VALUES (?, ?, ?)",
                ["EXAMPLE_G", month, json.dumps(record)],
            )
        yield db


def fake_provider(monkeypatch, result, captures):
    def complete(self, system, user):
        captures.append(json.loads(user))
        if len(captures) == 1:
            return '{"tools":["history","cash","debt"]}\nHere is the requested evidence plan.'
        return json.dumps(result)

    monkeypatch.setattr(OpenAICompatibleLLM, "complete", complete)


def test_actions_preserve_database_and_use_current_weights_and_dated_evidence(
    evidence_db, monkeypatch
):
    captures = []
    before = evidence_db.execute("SELECT * FROM score_observations").fetchall()
    chart = {**ChartConfig().model_dump(), "type": "bar", "months": 6, "color": "green"}
    fake_provider(
        monkeypatch,
        {
            "reply": "He ajustado los pesos de la vista y el gráfico.",
            "actions": [
                {"type": "set_weights", "weights": {**WEIGHTS, "financial": 0.8}},
                {"type": "set_chart", "chart": chart},
            ],
        },
        captures,
    )
    body = ViewChatRequest(
        entity_id="EXAMPLE_G",
        month="2025-02",
        message="Más peso financiero y barras verdes de seis meses",
        current_weights={"financial": 1, "liquidity": 0, "receivables": 0, "payables": 0},
    )
    result = run_view_chat(
        body, evidence_db, Settings(_env_file=None, helmcode_api_key="fake-key"), CONFIG
    )
    assert result.model_available
    assert result.actions[0].weights.financial == pytest.approx(0.8 / 1.4)
    assert sum(result.actions[0].weights.model_dump().values()) == pytest.approx(1)
    assert result.actions[1].chart.type == "bar"
    context = captures[-1]["context"]
    assert [
        {"month": row["month"], "displayed_level": row["displayed_level"]}
        for row in context["history"]
    ] == [
        {"month": "2025-01", "displayed_level": 80},
        {"month": "2025-02", "displayed_level": 80},
    ]
    assert len(context["cash"]["observations"]) == 2
    assert context["latest_observation"]["displayed_scoring"]["confidence"] == 50
    assert "snapshot" not in context["debt"]
    assert "777777" not in json.dumps(captures)
    assert "999999" not in json.dumps(captures)
    assert evidence_db.execute("SELECT * FROM score_observations").fetchall() == before


@pytest.mark.parametrize(
    "action",
    [
        {"type": "set_weights", "weights": {key: 0 for key in WEIGHTS}},
        {"type": "set_weights", "weights": {**WEIGHTS, "liquidity": -1}},
        {"type": "set_weights", "weights": {**WEIGHTS, "financial": True}},
        {"type": "set_weights", "weights": {key: 1e308 for key in WEIGHTS}},
        {"type": "set_weights", "weights": {**WEIGHTS, "generation": 1}},
        {"type": "set_chart", "chart": {"series": ["invented_metric"]}},
        {"type": "set_chart", "chart": {"type": "pie"}},
        {"type": "set_chart", "chart": {"months": 0}},
        {"type": "execute_sql", "sql": "DROP TABLE score_entities"},
        {"type": "set_chart", "chart": {"javascript": "alert(1)"}},
    ],
)
def test_invalid_model_action_never_reaches_browser(evidence_db, monkeypatch, action):
    fake_provider(monkeypatch, {"reply": "Done", "actions": [action]}, [])
    result = run_view_chat(
        ViewChatRequest(entity_id="EXAMPLE_G", message="change it"),
        evidence_db,
        Settings(_env_file=None, helmcode_api_key="fake-key"),
        CONFIG,
    )
    assert result.actions == []
    assert "No se ha cambiado" in result.reply


def test_disabled_weights_and_unsupported_request(evidence_db, monkeypatch):
    fake_provider(
        monkeypatch, {"reply": "Done", "actions": [{"type": "set_weights", "weights": WEIGHTS}]}, []
    )
    body = ViewChatRequest(entity_id="EXAMPLE_G", message="Change weights", allow_weights=False)
    settings = Settings(_env_file=None, helmcode_api_key="fake-key")
    assert run_view_chat(body, evidence_db, settings, CONFIG).actions == []
    fake_provider(
        monkeypatch,
        {
            "reply": "No puedo construir predicciones: solo hay observaciones históricas.",
            "actions": [],
        },
        [],
    )
    result = run_view_chat(body, evidence_db, settings, CONFIG)
    assert result.actions == []
    assert "predicciones" in result.reply


def test_manual_profile_uses_frozen_subscores_for_matching_view_context(evidence_db, monkeypatch):
    for month, raw in evidence_db.execute(
        "SELECT month, record_json FROM score_observations"
    ).fetchall():
        record = json.loads(raw)
        record["scoring"]["subscores"] = {
            key: {"score": score, "confidence": 100}
            for key, score in (
                ("generation", 99),
                ("debt_coverage", 1),
                ("activity", 40),
                ("conversion", 60),
            )
        }
        evidence_db.execute(
            "UPDATE score_observations SET record_json = ? WHERE month = ?",
            [json.dumps(record), month],
        )
    captures = []
    fake_provider(
        monkeypatch, {"reply": "La capacidad financiera pesa más.", "actions": []}, captures
    )
    result = run_view_chat(
        ViewChatRequest(
            entity_id="EXAMPLE_G",
            message="Explain current weights",
            current_weights={"financial": 1, "liquidity": 0, "receivables": 0, "payables": 0},
            current_profile={
                "level": WEIGHTS,
                "financial": {"generation": 1e307, "debt_coverage": 0},
                "evolution": {"activity": 0, "conversion": 1},
            },
        ),
        evidence_db,
        Settings(_env_file=None, helmcode_api_key="fake-key"),
        CONFIG,
    )
    assert result.actions == []
    latest = captures[-1]["context"]["latest_observation"]
    assert latest["displayed_level"] == 99
    assert latest["stored_level"] == 65
    assert latest["scoring"]["families"]["financial"]["score"] == 99
    assert latest["scoring"]["evolution"]["score"] == 60
    stored = json.loads(
        evidence_db.execute("SELECT record_json FROM score_observations LIMIT 1").fetchone()[0]
    )
    assert stored["scoring"]["families"]["financial"]["score"] == 80


def test_provider_failure_and_unconfigured_model_are_explicit(evidence_db, monkeypatch):
    body = ViewChatRequest(entity_id="EXAMPLE_G", message="Change weights")
    result = run_view_chat(
        body, evidence_db, Settings(_env_file=None, helmcode_api_key=None), CONFIG
    )
    assert result.actions == []
    assert not result.model_available
    assert "no está configurado" in result.reply

    def unavailable(self, system, user):
        raise TimeoutError("Provider unavailable")

    monkeypatch.setattr(OpenAICompatibleLLM, "complete", unavailable)
    result = run_view_chat(
        body, evidence_db, Settings(_env_file=None, helmcode_api_key="fake-key"), CONFIG
    )
    assert result.actions == []
    assert "No se ha cambiado" in result.reply


@pytest.mark.parametrize(
    "requested,months,cutoff,expected_series,liquidity_count",
    [
        (["liquidity"], None, "2025-03", [], 1),
        (["financial", "liquidity", "receivables"], None, "2025-03", ["financial"], 1),
        (["financial"], 1, "2025-03", [], 1),
        (["liquidity"], None, "2025-02", [], 0),
        (["financial"], 2, "2025-03", ["financial"], 1),
    ],
)
def test_chart_omits_sparse_series_in_requested_period(
    evidence_db, monkeypatch, requested, months, cutoff, expected_series, liquidity_count
):
    for month, raw in evidence_db.execute(
        "SELECT month, record_json FROM score_observations"
    ).fetchall():
        record = json.loads(raw)
        record["scoring"]["families"]["liquidity"]["score"] = 0 if month == "2025-03" else None
        evidence_db.execute(
            "UPDATE score_observations SET record_json = ? WHERE month = ?",
            [json.dumps(record), month],
        )
    before = evidence_db.execute("SELECT * FROM score_observations").fetchall()
    captures = []
    fake_provider(
        monkeypatch,
        {
            "reply": "He dibujado todas las series solicitadas.",
            "actions": [{"type": "set_chart", "chart": {"series": requested, "months": months}}],
        },
        captures,
    )
    result = run_view_chat(
        ViewChatRequest(entity_id="EXAMPLE_G", month=cutoff, message="Dibuja estas series"),
        evidence_db,
        Settings(_env_file=None, helmcode_api_key="fake-key"),
        CONFIG,
    )
    assert (
        captures[-1]["context"]["chart_availability"]["all_history_counts"]["liquidity"]
        == liquidity_count
    )
    if expected_series:
        assert result.actions[0].chart.series == expected_series
    else:
        assert result.actions == []
        assert "mantenido el gráfico actual" in result.reply
    if expected_series != requested:
        assert "al menos 2 observaciones" in result.reply
        assert "He dibujado todas" not in result.reply
    assert evidence_db.execute("SELECT * FROM score_observations").fetchall() == before


def test_chart_availability_uses_new_weights_when_combined_with_weight_change(
    evidence_db, monkeypatch
):
    fake_provider(
        monkeypatch,
        {
            "reply": "Updated both",
            "actions": [
                {"type": "set_chart", "chart": {"series": ["level"]}},
                {"type": "set_weights", "weights": {**dict.fromkeys(WEIGHTS, 0), "receivables": 1}},
            ],
        },
        [],
    )
    result = run_view_chat(
        ViewChatRequest(entity_id="EXAMPLE_G", message="Solo cuentas a cobrar y gráfico global"),
        evidence_db,
        Settings(_env_file=None, helmcode_api_key="fake-key"),
        CONFIG,
    )
    assert [action.type for action in result.actions] == ["set_weights"]
    assert "0 observaciones" in result.reply
    assert "actualizado los pesos" in result.reply


def test_endpoint_scope_and_validation(evidence_db):
    app = FastAPI()
    app.include_router(router)
    app.state.db = evidence_db
    app.state.tables = {"score_entities", "score_observations"}
    app.state.score_profile = {"config": CONFIG}
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/view-chats",
                json={"entity_id": "EXAMPLE_G' OR TRUE --", "message": "Explain"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/view-chats",
                json={"entity_id": "EXAMPLE_G", "message": "Explain", "month": "2024-01"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/view-chats",
                json={"entity_id": "EXAMPLE_G", "message": "Explain", "month": "2025-99"},
            ).status_code
            == 422
        )
        app.state.tables = set()
        assert (
            client.post(
                "/api/v1/view-chats", json={"entity_id": "EXAMPLE_G", "message": "Explain"}
            ).status_code
            == 503
        )
    get_settings.cache_clear()

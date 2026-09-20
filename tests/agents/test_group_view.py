"""Chat score preferences update every derived table without mutating shared data."""

import json

import duckdb
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from xray.agents.group_view import GroupViewRequest, _known_by, from_explicit, run_group_view
from xray.agents.llm import OpenAICompatibleLLM
from xray.api.routers.group_view import router
from xray.scoring.anchors import PILLAR_WEIGHTS
from xray.scoring.session import GroupWeights, evaluate_group
from xray.settings import Settings

CUSTOM = PILLAR_WEIGHTS | {"cash_generation": 0.5, "debt_burden": 0.05, "liquidity": 0.15}
SETTINGS = Settings(_env_file=None, helmcode_api_key="fake-key")


@pytest.fixture
def score_db():
    rows = pd.DataFrame(
        {
            "group_id": "EXAMPLE_GROUP",
            "month": pd.date_range("2025-01-01", periods=12, freq="MS"),
            "liquidity": 70.0,
            "payment_discipline": 70.0,
            "collections": 70.0,
            "cash_generation": [90 - 6 * i for i in range(12)],
            "debt_burden": 75.0,
            "monthly_inflow_eur": 100_000.0,
            "months_observed": range(1, 13),
            "level": 70.0,
            "level_uncapped": 70.0,
            "is_capped": False,
            "coverage": 1.0,
            "tier": "healthy",
            "state": "healthy",
            "trend": 0.0,
            "compound": 70.0,
            "level_smooth": 70.0,
        }
    )
    with duckdb.connect() as db:
        db.register("fixture", rows)
        db.execute("create table scores as select * from fixture")
        db.execute("create table drivers (group_id varchar, month timestamp, pillar varchar)")
        yield db


def test_preference_recalculates_history_drivers_alerts_and_offers_without_writes(
    score_db, monkeypatch
):
    before = score_db.execute("select * from scores").fetchall()
    monkeypatch.setattr(
        OpenAICompatibleLLM, "complete", lambda *args: json.dumps({"weights": CUSTOM})
    )
    result = run_group_view(
        GroupViewRequest(
            group_id="EXAMPLE_GROUP",
            month="2025-12-01",
            message="Me importa más la generación de caja que cómo de endeudada está una empresa. "
            "Modifica los pesos.",
        ),
        score_db,
        SETTINGS,
    )
    action = result["actions"][0]
    tables = action["tables"]
    assert action["type"] == "set_group_weights"
    assert sum(action["weights"].values()) == pytest.approx(1)
    expected = 0.15 * 70 + 0.2 * 70 + 0.5 * 24 + 0.1 * 70 + 0.05 * 75
    latest = tables["scores"][-1]
    assert latest["level"] == pytest.approx(expected)
    assert latest["trend"] < 0
    assert latest["state"] == "falling"
    assert tables["alerts"]
    for row in tables["scores"]:
        drivers = [d for d in tables["drivers"] if d["month"] == row["month"]]
        assert 50 + sum(d["contribution"] for d in drivers) == pytest.approx(row["level_uncapped"])
    baseline = evaluate_group(score_db, "EXAMPLE_GROUP", GroupWeights(**PILLAR_WEIGHTS))
    assert tables["offers"][-1]["limit_eur"] != baseline["offers"][-1]["limit_eur"]
    move = next(
        a
        for a in tables["actions"]
        if a["month"] == "2025-12-01" and a["pillar"] == "cash_generation"
    )
    assert move["expected_level_gain"] == pytest.approx(0.4 * (70 - 24) * 0.5)
    assert score_db.execute("select * from scores").fetchall() == before
    assert PILLAR_WEIGHTS["cash_generation"] == 0.2


def test_followup_uses_active_weights_and_only_past_evidence(score_db, monkeypatch):
    calls = []

    def complete(self, system, user):
        calls.append(json.loads(user))
        return '{"weights": null}' if len(calls) == 1 else "Respuesta con los pesos activos."

    monkeypatch.setattr(OpenAICompatibleLLM, "complete", complete)
    result = run_group_view(
        GroupViewRequest(
            group_id="EXAMPLE_GROUP",
            month="2025-07-01",
            message="¿Por qué baja ahora?",
            current_weights=GroupWeights(**CUSTOM),
        ),
        score_db,
        SETTINGS,
    )
    assert result["actions"] == []
    assert calls[-1]["weights"]["cash_generation"] == 0.5
    evidence = calls[-1]["evidence"]
    assert all(row["month"] <= "2025-07-01" for rows in evidence.values() for row in rows)
    assert evidence["scores"][-1]["level"] == pytest.approx(62.25)
    assert all("resolution" not in row for row in evidence["alerts"])


def test_portfolio_question_keeps_existing_fleet(score_db, monkeypatch):
    monkeypatch.setattr(
        OpenAICompatibleLLM, "complete", lambda *args: '{"weights": null, "analyze_current": false}'
    )
    result = run_group_view(
        GroupViewRequest(
            group_id="EXAMPLE_GROUP",
            month="2025-12-01",
            message="¿Qué grupos de la cartera están cayendo?",
        ),
        score_db,
        SETTINGS,
    )
    assert result == {"handled": False, "actions": []}


def test_portfolio_question_reaches_the_fleet_with_custom_weights_too(score_db, monkeypatch):
    monkeypatch.setattr(
        OpenAICompatibleLLM, "complete", lambda *args: '{"weights": null, "analyze_current": false}'
    )
    result = run_group_view(
        GroupViewRequest(
            group_id="EXAMPLE_GROUP",
            month="2025-12-01",
            message="Which groups are improving the most?",
            current_weights=GroupWeights(**CUSTOM),
        ),
        score_db,
        SETTINGS,
    )
    assert result == {"handled": False, "actions": []}


def test_an_alert_shows_its_outcome_only_once_the_outcome_has_happened():
    alert = {
        "month": "2026-06-01",
        "tier_change_month": "2026-08-01",
        "anticipation_months": 2.0,
        "late": False,
        "resolution": "",
        "resolution_month": None,
    }
    assert _known_by(alert, "2026-07-01") == {"month": "2026-06-01"}
    assert _known_by(alert, "2026-08-01")["anticipation_months"] == 2.0


def test_explain_this_uses_exact_displayed_card_without_changing_weights(score_db, monkeypatch):
    calls = []

    def complete(self, system, user):
        calls.append(json.loads(user))
        return '{"weights": null}' if len(calls) == 1 else "El score de tu ficha es 70."

    monkeypatch.setattr(OpenAICompatibleLLM, "complete", complete)
    before = score_db.execute("select * from scores").fetchall()
    result = run_group_view(
        GroupViewRequest(
            group_id="EXAMPLE_GROUP",
            month="2025-07-01",
            message="Explícame esto",
        ),
        score_db,
        SETTINGS,
    )
    assert result["actions"] == []
    assert calls[-1]["context"]["entity_id"] == "EXAMPLE_GROUP"
    assert calls[-1]["context"]["month"] == "2025-07-01"
    assert calls[-1]["evidence"]["scores"][-1]["level"] == 70
    assert len(calls[-1]["evidence"]["scores"]) == 7
    assert score_db.execute("select * from scores").fetchall() == before


@pytest.fixture
def company_db(score_db):
    score_db.execute("""create table companies as
        select 'EXAMPLE_COMPANY' company_id, 'Example Company' as name, 'EXAMPLE_GROUP' group_id
        union all select 'OTHER_COMPANY', 'Other Company', 'OTHER_GROUP'""")
    score_db.execute("""create table company_scores as
        select *, 'EXAMPLE_COMPANY' company_id from scores
        union all select *, 'OTHER_COMPANY' company_id from scores""")
    score_db.execute("update company_scores set level=31 where company_id='EXAMPLE_COMPANY'")
    score_db.execute(
        "update company_scores set group_id='OTHER_GROUP' where company_id='OTHER_COMPANY'"
    )
    return score_db


def test_company_analysis_and_followups_use_own_card_and_cutoff(company_db, monkeypatch):
    calls = []

    def complete(self, system, user):
        calls.append(json.loads(user))
        return "La filial está en 31."

    monkeypatch.setattr(OpenAICompatibleLLM, "complete", complete)
    history = [
        {"role": "user", "content": "Explícame esto"},
        {"role": "assistant", "content": "La filial está en 31."},
    ]
    result = run_group_view(
        GroupViewRequest(
            group_id="EXAMPLE_GROUP",
            company_id="EXAMPLE_COMPANY",
            month="2025-05-01",
            message="¿Y por qué?",
            history=history,
            current_weights=GroupWeights(**CUSTOM),
        ),
        company_db,
        SETTINGS,
    )
    assert result["actions"] == []
    assert calls[0]["context"]["kind"] == "company"
    assert calls[0]["context"]["name"] == "Example Company"
    assert calls[0]["context"]["active_weights"] == PILLAR_WEIGHTS
    assert calls[0]["history"] == history
    scores = calls[0]["evidence"]["scores"]
    assert len(scores) == 5
    assert all(row["company_id"] == "EXAMPLE_COMPANY" and row["level"] == 31 for row in scores)
    assert "offers" not in calls[0]["evidence"]
    assert "impact" not in calls[0]["evidence"]


@pytest.mark.parametrize("company_id", ["OTHER_COMPANY", "UNKNOWN_COMPANY"])
def test_company_must_belong_to_selected_group(company_db, company_id):
    with pytest.raises(LookupError, match="selected group"):
        run_group_view(
            GroupViewRequest(
                group_id="EXAMPLE_GROUP",
                company_id=company_id,
                month="2025-05-01",
                message="Explícame esto",
            ),
            company_db,
            SETTINGS,
        )


def test_custom_weights_keep_safety_cap_and_renormalize_missing_pillars(score_db):
    score_db.execute(
        "update scores set liquidity = 10, payment_discipline = null, collections = null"
    )
    result = evaluate_group(score_db, "EXAMPLE_GROUP", GroupWeights(**CUSTOM))
    first = result["scores"][0]
    assert first["coverage"] == pytest.approx(0.7)
    assert first["is_capped"]
    assert first["level"] == 50
    assert first["level_uncapped"] > 50
    assert not any(d["pillar"] == "collections" for d in result["drivers"])


def test_evaluation_api_rejects_invalid_weights_and_missing_group(score_db):
    app = FastAPI()
    app.state.db = score_db
    app.include_router(router)
    with TestClient(app) as client:
        path = "/api/v1/groups/EXAMPLE_GROUP/evaluations"
        assert client.post(path, json=CUSTOM).status_code == 200
        for weights in (
            {},
            {p: 0 for p in CUSTOM},
            CUSTOM | {"debt_burden": -1},
            CUSTOM | {"fake": 1},
        ):
            assert client.post(path, json=weights).status_code == 422
        assert client.post("/api/v1/groups/unknown/evaluations", json=CUSTOM).status_code == 404
        score_db.execute("update scores set cash_generation = null")
        unsupported = {p: float(p == "cash_generation") for p in CUSTOM}
        assert client.post(path, json=unsupported).status_code == 422


def test_a_stated_percentage_is_kept_and_the_rest_is_shared_as_it_stood():
    weights = from_explicit({"liquidity": 50}, GroupWeights(**PILLAR_WEIGHTS)).model_dump()

    assert weights["liquidity"] == pytest.approx(0.5)
    assert weights["payment_discipline"] == pytest.approx(2 * weights["collections"])
    assert sum(weights.values()) == pytest.approx(1)


@pytest.mark.parametrize(
    "asked", [{"liquidity": 200}, {"debt_burden": -30}, {"liquidity": 70, "collections": 60}]
)
def test_an_impossible_percentage_is_refused(asked):
    with pytest.raises(ValueError):
        from_explicit(asked, GroupWeights(**PILLAR_WEIGHTS))


def test_prose_instead_of_a_plan_changes_nothing(score_db, monkeypatch):
    answers = iter(["That is a question, not an instruction.", "An analysis."])
    monkeypatch.setattr(OpenAICompatibleLLM, "complete", lambda *args: next(answers))

    result = run_group_view(
        GroupViewRequest(group_id="EXAMPLE_GROUP", month="2025-12-01", message="is 90% sensible?"),
        score_db,
        SETTINGS,
    )

    assert result == {"reply": "An analysis.", "actions": []}

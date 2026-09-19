"""Financial invariants for the local preview scorecard."""

import pytest

from xray.v2_scores import aggregate, curve, load_score_config, score_entity


def entity(inflow: float = 120, cost: float = 80, debt: float = 20) -> dict:
    return {
        "monthly": [
            {
                "inflow": inflow,
                "outflow": cost + debt,
                "debt_service": debt,
                "total_companies": 2,
                "flow_companies": 2,
                "perimeter_changed": False,
            }
            for _ in range(12)
        ]
    }


def test_curves_interpolate_clamp_and_preserve_missing():
    anchors = load_score_config()["curves"]["liquidity"]
    assert [curve(x, anchors) for x in (None, -10, 22.5, 150)] == [None, 0, 37.5, 100]


def test_repayment_is_not_deducted_twice():
    low = score_entity(entity())[-1]
    high = score_entity(entity(debt=60))[-1]
    assert low["subscores"]["generation"]["score"] == 100
    assert high["subscores"]["generation"]["score"] == 100
    assert high["families"]["financial"]["score"] == pytest.approx(73.611111)
    assert high["metrics"]["net_after_debt"] == -60
    assert low["metrics"]["net_after_debt"] == 60


def test_zero_debt_preserves_available_generation_and_nominal_confidence():
    scored = score_entity(entity(debt=0))[-1]
    assert scored["subscores"]["debt_coverage"]["score"] is None
    assert scored["subscores"]["debt_coverage"]["confidence"] == 0
    assert scored["metrics"]["debt_service"] == 0
    assert scored["families"]["financial"]["score"] == pytest.approx(100)
    assert scored["families"]["financial"]["confidence"] == pytest.approx(100 * 2 / 3)
    assert scored["level"]["confidence"] == pytest.approx(100 * 0.4 * 2 / 3)


def test_missing_components_do_not_turn_into_bad_health():
    scored = score_entity({"monthly": [{}]})[0]
    assert scored["level"]["score"] is None
    assert scored["level"]["confidence"] == 0
    assert scored["level"]["coverage"] == 0
    partial = score_entity(entity())[-1]
    assert partial["level"]["score"] == 100
    assert partial["level"]["confidence"] == 40


def test_weights_change_health_without_multiplying_by_confidence():
    nodes = {"a": {"score": 100, "confidence": 20}, "b": {"score": 0, "confidence": 80}}
    assert aggregate(nodes, {"a": 1, "b": 1})["score"] == 50
    assert aggregate(nodes, {"a": 3, "b": 1})["score"] == 75
    with pytest.raises(ValueError, match="positive weight"):
        aggregate(nodes, {"a": 0, "b": 0})


def test_invoice_score_uses_invoice_mass_and_unknown_due_range():
    data = entity()
    data["monthly"][-1].update(
        rec_companies=1, rec_open=200, rec_known_due_open=100, rec_score_mass=7500
    )
    leaf = score_entity(data)[-1]["subscores"]["receivables"]
    assert leaf["score"] == 75
    assert leaf["score_range"] == [37.5, 87.5]
    assert leaf["perimeter"] == 0.25
    assert leaf["quality"] == 0.5


def test_evolution_requires_comparable_six_month_window():
    data = entity(inflow=100, cost=50, debt=0)
    for row in data["monthly"][-3:]:
        row.update(inflow=200, outflow=110)
    result = score_entity(data)[-1]
    assert result["evolution"]["score"] == pytest.approx(50.7142857)
    data["monthly"][-2]["perimeter_changed"] = True
    assert score_entity(data)[-1]["evolution"]["score"] is None


def test_group_partial_perimeter_reduces_evidence_not_health():
    data = entity()
    full = score_entity(data)[-1]
    for row in data["monthly"]:
        row["flow_companies"] = 1
    partial = score_entity(data)[-1]
    assert partial["level"]["score"] == full["level"]["score"]
    assert partial["level"]["confidence"] == full["level"]["confidence"] / 2
    data["currency_mixed"] = True
    assert score_entity(data)[-1]["level"]["score"] is None


def test_invoice_history_requires_emissions_and_fx_quality_is_estimated():
    data = entity()
    data["fx_estimated"] = True
    for row in data["monthly"]:
        row.update(
            rec_companies=2,
            rec_open=100,
            rec_known_due_open=100,
            rec_score_mass=7500,
            rec_invoice_count=0,
            tx_count=10,
            excluded_tx_count=2,
        )
    data["monthly"][0]["rec_invoice_count"] = 1
    result = score_entity(data)[-1]
    assert result["subscores"]["receivables"]["history"] == pytest.approx(1 / 12)
    assert result["subscores"]["generation"]["quality"] == 0.5
    assert result["subscores"]["generation"]["perimeter"] == 0.8


def test_partial_fx_caps_registered_perimeter():
    data = entity()
    data.update(
        fx_partial=True,
        fx_estimated=True,
        fx_covered_companies=1,
        members=["Example A", "Example B"],
    )
    result = score_entity(data)[-1]
    assert result["subscores"]["generation"]["perimeter"] == 0.5
    assert result["subscores"]["generation"]["confidence"] == 25


def test_future_fx_metadata_does_not_change_earlier_months():
    data = entity()
    for row in data["monthly"]:
        row["fx_estimated_tx_count"] = 0
    earlier = score_entity(data)[8]
    data.update(fx_estimated=True, fx_partial=True, fx_covered_companies=0)
    data["monthly"][-1]["fx_estimated_tx_count"] = 1
    revised = score_entity(data)
    assert revised[8] == earlier
    assert revised[-1]["subscores"]["generation"]["quality"] == 0.5
    assert revised[-1]["subscores"]["activity"]["quality"] == 0.5

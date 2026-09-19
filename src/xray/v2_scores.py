"""Configurable local score preview, with evidence kept separate from health."""

import json
from math import isfinite
from pathlib import Path


def load_score_config() -> dict:
    """Load the versioned anchors and evidence assumptions shared with the UI."""
    return json.loads(Path(__file__).with_name("v2_score_config.json").read_text(encoding="utf-8"))


def curve(value: float | None, anchors: list[list[float]]) -> float | None:
    """Interpolate linearly and clamp to the endpoint scores."""
    if value is None or not isfinite(value):
        return None
    if value <= anchors[0][0]:
        return float(anchors[0][1])
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:], strict=False):
        if value <= x1:
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return float(anchors[-1][1])


def aggregate(nodes: dict[str, dict], weights: dict[str, float]) -> dict:
    """Renormalize health only; missing nodes retain their nominal evidence budget."""
    if any(not isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError("Weights must be finite and nonnegative")
    nominal = sum(weights.values())
    if nominal <= 0:
        raise ValueError("Choose at least one positive weight")
    selected = [(nodes[k], w) for k, w in weights.items() if w > 0]
    valid = [(node, w) for node, w in selected if node["score"] is not None]
    available_weight = sum(w for _, w in valid)
    confidence = (
        sum(w * node["confidence"] for node, w in valid) / nominal
        if nominal and all(node["confidence"] is not None for node, _ in valid)
        else None
    )
    return {
        "score": sum(w * node["score"] for node, w in valid) / available_weight
        if available_weight
        else None,
        "confidence": confidence,
        "coverage": sum(w * node.get("coverage", 1) for node, w in valid) / nominal
        if nominal
        else 0,
        "available": len(valid),
        "expected": len(selected),
    }


def _leaf(
    score: float | None,
    raw: float | None,
    history: float,
    perimeter: float | None,
    quality: float,
    reason: str,
) -> dict:
    return {
        "score": score,
        "raw_value": raw,
        "confidence": (
            0
            if score is None
            else 100 * history * perimeter * quality
            if perimeter is not None
            else None
        ),
        "coverage": int(score is not None),
        "available": int(score is not None),
        "expected": 1,
        "history": history,
        "perimeter": perimeter,
        "quality": quality,
        "reason": reason,
    }


def _perimeter(rows: list[dict], field: str) -> float | None:
    if not rows or any(r.get(field) is None or not r.get("total_companies") for r in rows):
        return None
    coverage = min(min(1, r[field] / r["total_companies"]) for r in rows)
    if field == "flow_companies":
        received = [
            1 - r.get("excluded_tx_count", 0) / r["tx_count"]
            for r in rows
            if r.get("tx_count", 0) > 0
        ]
        if received:
            coverage = min(coverage, *received)
    return coverage


def score_entity(entity: dict, config: dict | None = None) -> list[dict]:
    """Score existing monthly observations without rebuilding cash or converting currencies."""
    config = config or load_score_config()
    curves, weights = config["curves"], config["weights"]
    reference = config["history"]["reference_months"]
    flow_min = config["history"]["flow_minimum"]
    evolution_min = config["history"]["evolution_minimum"]
    quality = config["quality"]
    results = []
    usable_run = 0
    side_runs = {"rec": 0, "pay": 0}
    rows = entity["monthly"]
    for i, row in enumerate(rows):
        flow_valid = all(row.get(k) is not None for k in ("inflow", "outflow", "debt_service"))
        usable_run = usable_run + 1 if flow_valid else 0
        history = min(1, usable_run / reference)
        recent = rows[max(0, i - flow_min + 1) : i + 1]
        monthly_fx = "fx_estimated_tx_count" in row
        flow_estimated = (
            any(r.get("fx_estimated_tx_count", 0) > 0 for r in recent)
            if monthly_fx
            else entity.get("fx_estimated", False)
        )
        flow_quality = quality["estimated"] if flow_estimated else quality["observed"]
        perimeter = _perimeter(recent, "flow_companies")
        ready = usable_run >= flow_min and not entity.get("currency_mixed", False)
        metrics = {
            "inflow": None,
            "outflow": None,
            "debt_service": None,
            "cost_before_debt": None,
            "generation_before_debt": None,
            "net_after_debt": None,
        }
        z = q = None
        if ready:
            inflow, outflow, debt = (
                sum(r[k] for r in recent) for k in ("inflow", "outflow", "debt_service")
            )
            cost = outflow - debt
            generated = inflow - cost
            metrics.update(
                inflow=inflow,
                outflow=outflow,
                debt_service=debt,
                cost_before_debt=cost,
                generation_before_debt=generated,
                net_after_debt=generated - debt,
            )
            z = generated / (inflow + cost) if inflow + cost > 0 else None
            q = generated / debt if debt > 0 else None
        subscores = {}
        for name, raw in (("generation", z), ("debt_coverage", q)):
            reason = "observed_3m" if raw is not None else "insufficient_flow_history"
            if ready and raw is None:
                reason = (
                    "zero_observed_debt_service"
                    if name == "debt_coverage"
                    else "zero_observed_base"
                )
            subscores[name] = _leaf(
                curve(raw, curves[name]), raw, history, perimeter, flow_quality, reason
            )
        cash_total = entity.get("liquid_accounts_total", 0)
        cash_perimeter = (
            entity.get("liquid_accounts_covered", 0) / cash_total if cash_total else None
        )
        liquidity_perimeter = (
            min(perimeter, cash_perimeter)
            if perimeter is not None and cash_perimeter is not None
            else None
        )
        buffer = row.get("buffer_days") if row.get("cash_date") and ready else None
        subscores["liquidity"] = _leaf(
            curve(buffer, curves["liquidity"]),
            buffer,
            history,
            liquidity_perimeter,
            quality["estimated"]
            if row.get("cash_date") and entity.get("cash_fx_estimated")
            else flow_quality,
            "dated_cash_snapshot" if buffer is not None else "snapshot_or_positive_outflow_missing",
        )
        if not row.get("cash_date"):
            subscores["liquidity"]["confidence"] = 0
        for prefix, name in (("rec", "receivables"), ("pay", "payables")):
            side_runs[prefix] += int((row.get(f"{prefix}_invoice_count") or 0) > 0)
            opened = row.get(f"{prefix}_open")
            known = row.get(f"{prefix}_known_due_open")
            mass = row.get(f"{prefix}_score_mass")
            score = mass / known if known is not None and known > 0 and mass is not None else None
            p = _perimeter([row], f"{prefix}_companies")
            if p is not None and opened is not None and opened > 0 and known is not None:
                p *= known / opened
            reason = (
                "estimated_open_invoices"
                if score is not None
                else "missing_invoice_dates_or_source"
            )
            if opened == 0:
                reason = "zero_observed_open_balance"
            leaf = _leaf(
                score, score, min(1, side_runs[prefix] / reference), p, quality["estimated"], reason
            )
            leaf["score_range"] = (
                [mass / opened, (mass + 100 * (opened - known)) / opened]
                if opened and mass is not None and known is not None
                else None
            )
            if known is not None and opened and known < opened:
                leaf["reason"] = "known_due_subset_unknown_dates_range"
            subscores[name] = leaf
            leaf["history_basis"] = "months_with_issued_documents_proxy_not_feed_continuity"
            if entity.get("currency_mixed", False):
                leaf.update(
                    score=None,
                    confidence=0,
                    coverage=0,
                    available=0,
                    score_range=None,
                    reason="incompatible_currencies",
                )
        evolution_rows = rows[max(0, i - evolution_min + 1) : i + 1]
        evolution_estimated = (
            any(r.get("fx_estimated_tx_count", 0) > 0 for r in evolution_rows)
            if monthly_fx
            else entity.get("fx_estimated", False)
        )
        comparable = usable_run >= evolution_min and not any(
            r.get("perimeter_changed", True) for r in evolution_rows[1:]
        )
        growth = conversion = None
        if comparable and ready:
            previous = evolution_rows[:-flow_min]
            old_inflow = sum(r["inflow"] for r in previous)
            old_generated = old_inflow - sum(r["outflow"] - r["debt_service"] for r in previous)
            if old_inflow > 0:
                growth = metrics["inflow"] / old_inflow - 1
            if old_inflow > 0 and metrics["inflow"] > 0:
                conversion = 100 * (
                    metrics["generation_before_debt"] / metrics["inflow"]
                    - old_generated / old_inflow
                )
            metrics.update(
                previous_inflow=old_inflow, previous_generation_before_debt=old_generated
            )
        for name, raw in (("activity", growth), ("conversion", conversion)):
            subscores[name] = _leaf(
                curve(raw, curves[name]),
                raw,
                history,
                _perimeter(evolution_rows, "flow_companies"),
                quality["estimated"] if evolution_estimated else quality["observed"],
                "observed_3m_previous_3m"
                if raw is not None
                else "history_perimeter_or_positive_base_missing",
            )
        if entity.get("fx_partial") and not monthly_fx:
            members = len(entity.get("members", []))
            fx_perimeter = entity.get("fx_covered_companies", 0) / members if members else None
            for leaf in subscores.values():
                leaf["perimeter"] = (
                    min(leaf["perimeter"], fx_perimeter)
                    if leaf["perimeter"] is not None and fx_perimeter is not None
                    else None
                )
                leaf["confidence"] = (
                    0
                    if leaf["score"] is None
                    else 100 * leaf["history"] * leaf["perimeter"] * leaf["quality"]
                    if leaf["perimeter"] is not None
                    else None
                )
        families = {
            "financial": aggregate(subscores, weights["financial"]),
            **{name: subscores[name] for name in ("liquidity", "receivables", "payables")},
        }
        results.append(
            {
                "version": config["version"],
                "subscores": subscores,
                "families": families,
                "level": aggregate(families, weights["level"]),
                "evolution": aggregate(subscores, weights["evolution"]),
                "metrics": metrics,
            }
        )
    return results

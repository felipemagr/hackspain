"""Isolated local scorecard and reversible weight evaluation."""

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from xray.scoring.local_serving import read_entity, reweight_entity

router = APIRouter(prefix="/api/v1/scoring", tags=["scoring"])


class Evaluation(BaseModel):
    """Partial overrides for the three configurable aggregation families."""

    model_config = ConfigDict(extra="forbid")
    weights: dict[str, dict[str, float]]


def _profile(request: Request) -> dict:
    if (
        not {"score_entities", "score_observations"}.issubset(request.app.state.tables)
        or not request.app.state.score_profile
    ):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Local scoring export unavailable")
    return request.app.state.score_profile


@router.get("/config")
def config(request: Request) -> dict:
    """Return the exported scorecard configuration and provenance."""
    profile = _profile(request)
    return {**profile["config"], "provenance": profile["provenance"]}


@router.get("/entities")
def entities(
    request: Request,
    kind: Literal["company", "group"] = "company",
    query: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=2000),
) -> dict:
    """List current scores without sending historical records."""
    _profile(request)
    db = request.app.state.db.cursor()
    try:
        params = [kind, query, query]
        where = (
            "e.kind = ? AND (contains(lower(e.name), lower(?)) "
            "OR contains(lower(e.entity_id), lower(?)))"
        )
        total = db.execute(
            f"SELECT count(*) FROM score_entities e WHERE {where}", params
        ).fetchone()[0]
        rows = db.execute(
            "SELECT e.entity_id, e.kind, e.group_id, e.name, e.currency, e.member_count, "
            "o.level, o.confidence, o.month FROM score_entities e LEFT JOIN "
            "(SELECT * FROM score_observations QUALIFY row_number() OVER "
            "(PARTITION BY entity_id ORDER BY month DESC) = 1) o "
            f"ON e.entity_id = o.entity_id WHERE {where} ORDER BY e.entity_id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        keys = (
            "id",
            "kind",
            "group_id",
            "name",
            "currency",
            "member_count",
            "level",
            "confidence",
            "month",
        )
        return {
            "data": [dict(zip(keys, row, strict=True)) for row in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }
    finally:
        db.close()


@router.get("/entities/{entity_id}")
def entity_detail(entity_id: str, request: Request) -> dict:
    """Read one company's or group's observed monthly score series."""
    profile = _profile(request)
    db = request.app.state.db.cursor()
    try:
        detail = read_entity(db, entity_id, config=profile["config"])
    finally:
        db.close()
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    return detail


@router.get("/portfolio")
def portfolio(request: Request, kind: Literal["company", "group"] = "group") -> dict:
    """Return complete history with score-only nodes; entity detail carries node evidence."""
    profile = _profile(request)
    subscore_names = (
        "generation",
        "debt_coverage",
        "liquidity",
        "receivables",
        "payables",
        "activity",
        "conversion",
    )
    family_names = ("financial", "liquidity", "receivables", "payables")
    paths = ["$.scoring.evolution.confidence", "$.scoring.level.coverage"] + [
        f"$.scoring.{collection}.{name}.score"
        for collection, names in (("subscores", subscore_names), ("families", family_names))
        for name in names
    ]
    with request.app.state.db.cursor() as db:
        metadata = db.execute(
            "SELECT metadata_json FROM score_entities WHERE kind = ? ORDER BY entity_id", [kind]
        ).fetchall()
        rows = db.execute(
            "SELECT entity_id, month, level, confidence, evolution, "
            "json_extract(record_json, ?) FROM score_observations "
            "WHERE kind = ? ORDER BY entity_id, month",
            [paths, kind],
        ).fetchall()
    observations = []
    for entity_id, month, level, confidence, evolution, extracted in rows:
        values = [json.loads(value) if value is not None else None for value in extracted]
        observations.append(
            {
                "entity_id": entity_id,
                "month": month,
                "level": level,
                "confidence": confidence,
                "evolution": evolution,
                "evolution_confidence": values[0],
                "coverage": values[1],
                "subscores": {
                    name: {"score": value}
                    for name, value in zip(subscore_names, values[2:9], strict=True)
                },
                "families": {
                    name: {"score": value}
                    for name, value in zip(family_names, values[9:], strict=True)
                },
            }
        )
    return {
        "entities": [json.loads(row[0]) for row in metadata],
        "observations": observations,
        "config": profile["config"],
    }


@router.post("/entities/{entity_id}/evaluate")
def evaluate(entity_id: str, body: Evaluation, request: Request) -> dict:
    """Recompute the selected series with temporary weights."""
    detail = entity_detail(entity_id, request)
    try:
        return reweight_entity(detail, body.weights)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

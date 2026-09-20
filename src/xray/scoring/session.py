"""Recalculate a group's serving tables with session weights, without publishing them."""

import json
from math import isfinite
from typing import Annotated

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from xray.scoring.anchors import PILLAR_WEIGHTS
from xray.scoring.monitor import detect
from xray.scoring.offer import actions, offers
from xray.scoring.score import level

Weight = Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)]


class GroupWeights(BaseModel):
    """A complete positive budget over the five baseline pillars."""

    model_config = ConfigDict(extra="forbid")
    liquidity: Weight
    payment_discipline: Weight
    cash_generation: Weight
    collections: Weight
    debt_burden: Weight

    @model_validator(mode="after")
    def normalize(self) -> "GroupWeights":
        total = sum(self.model_dump().values())
        if total <= 0 or not isfinite(total):
            raise ValueError("At least one pillar must have positive weight")
        for name, value in self.model_dump().items():
            setattr(self, name, value / total)
        return self


def records(frame: pd.DataFrame) -> list[dict]:
    """JSON-safe records with the same month format as the web store."""
    frame = frame.copy()
    for column in frame.select_dtypes(include=["datetime", "datetimetz"]):
        frame[column] = frame[column].dt.strftime("%Y-%m-%d")
    return json.loads(frame.to_json(orient="records"))


def evaluate_group(
    db: duckdb.DuckDBPyConnection, group_id: str, weights: GroupWeights
) -> dict[str, list[dict]] | None:
    """Reblend stored pillars and replay every score-dependent group output."""
    with db.cursor() as cursor:
        source = cursor.execute(
            "select * from scores where group_id = ? order by month", [group_id]
        ).df()
        original_drivers = cursor.execute(
            "select * from drivers where group_id = ?", [group_id]
        ).df()
        size_rank = cursor.execute(
            """select size_rank from (
                select group_id, cume_dist() over (order by median(monthly_inflow_eur)) size_rank
                from scores group by group_id) where group_id = ?""",
            [group_id],
        ).fetchone()
    if source.empty:
        return None
    budget = weights.model_dump()
    source["month"] = pd.to_datetime(source["month"])
    recalculated = level(source, weights=budget)
    if (recalculated["coverage"] <= 0).any():
        raise ValueError("Los pesos elegidos dejan meses sin ningún pilar con datos.")
    keys = ["group_id", "month"]
    derived = ["level_smooth", "trend", "compound", "state", "onset_month"]
    scores = source.drop(
        columns=[c for c in recalculated if c not in keys] + derived, errors="ignore"
    ).merge(recalculated, on=keys)
    trajectory, alerts = detect(scores)
    scores = scores.merge(trajectory.drop(columns="onset_month"), on=keys)
    if not alerts.empty:
        alerts["severity"] = (alerts["severity"] * size_rank[0]).round(1)
    drivers = scores.melt(keys, list(PILLAR_WEIGHTS), "pillar", "score").dropna(subset=["score"])
    contributions = scores.melt(
        keys, [f"contrib_{p}" for p in PILLAR_WEIGHTS], "pillar", "contribution"
    )
    contributions["pillar"] = contributions["pillar"].str.removeprefix("contrib_")
    drivers = drivers.merge(contributions, on=keys + ["pillar"])
    if "headline" in original_drivers:
        original_drivers["month"] = pd.to_datetime(original_drivers["month"])
        drivers = drivers.merge(original_drivers[keys + ["pillar", "headline"]], how="left")
    drivers = drivers.sort_values(["pillar", "month"])
    by = drivers.groupby("pillar")
    drivers["delta_score"] = by["score"].diff()
    drivers["delta_contribution"] = by["contribution"].diff()
    # Actions are served for every month so moving the date keeps their evidence causal.
    moves = pd.concat([actions(g, budget) for _, g in scores.groupby("month")], ignore_index=True)
    return {
        "scores": records(scores[list(source.columns)]),
        "drivers": records(drivers),
        "alerts": records(alerts),
        "offers": records(offers(scores)),
        "actions": records(moves),
    }

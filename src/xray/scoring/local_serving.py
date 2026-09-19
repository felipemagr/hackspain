"""Export and query the isolated local scorecard without changing V2 artifacts."""

import argparse
import copy
import hashlib
import json
from math import isfinite
from pathlib import Path

import duckdb

from xray.config import PROCESSED_DATA_DIR
from xray.v2_scores import score_entity


def file_hash(path: Path) -> str:
    """Hash large inputs without loading them into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_payload() -> tuple[dict, dict]:
    """Reuse V2 only when every current input and its output match its manifest."""
    from xray import v2

    source = Path(v2.__file__).parent
    inputs = [PROCESSED_DATA_DIR / f"{name}.parquet" for name in v2.TABLES] + [
        source / "v2.py",
        source / "templates/mvp_v2.html",
        source / "v2_scores.py",
        source / "v2_score_config.json",
        source / "v2_fx.py",
        source / "v2_fx_rates.csv",
    ]
    hashes = {path.name: file_hash(path) for path in inputs}
    html = PROCESSED_DATA_DIR / "xray-v2.html"
    manifest_path = PROCESSED_DATA_DIR / "xray-v2.manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    provenance = {
        "inputs": hashes,
        "original_v2_manifest": manifest,
        "exporter_sha256": file_hash(Path(__file__)),
    }
    if (
        manifest.get("inputs") == hashes
        and html.exists()
        and file_hash(html) == manifest.get("output_sha256")
    ):
        content = html.read_text(encoding="utf-8")
        marker = '<script type="application/json" id="xray-data">'
        payload = json.loads(content.split(marker, 1)[1].split("</script>", 1)[0])
        provenance["source"] = "verified_v2_cache"
        return payload, provenance
    import pandas as pd

    from xray.v2_fx import normalize_tables_eur

    tables = {name: pd.read_parquet(PROCESSED_DATA_DIR / f"{name}.parquet") for name in v2.TABLES}
    tables, fx = normalize_tables_eur(tables)
    payload = v2.build_payload(tables)
    payload["fx_metadata"] = fx
    for entity in payload["entities"].values():
        members = [fx["by_company"][member] for member in entity["members"]]
        entity.update(
            original_currency=sorted(
                {m["native_currency"] for m in members if m["native_currency"]}
            ),
            fx_estimated=any(m["fx_estimated"] for m in members),
            fx_partial=any(m["partial"] for m in members),
            fx_covered_companies=sum(not m["partial"] for m in members),
        )
        for record, scoring in zip(
            entity["monthly"], score_entity(entity, payload["score_config"]), strict=True
        ):
            record["scoring"] = scoring
    provenance["source"] = "rebuilt_current_inputs"
    return payload, provenance


def export_payload(payload: dict, output_dir: Path, provenance: dict) -> None:
    """Write entity metadata and monthly records as independently queryable parquet."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as db:
        db.execute(
            "CREATE TABLE score_entities (entity_id VARCHAR, kind VARCHAR, group_id VARCHAR, "
            "name VARCHAR, currency VARCHAR, member_count INTEGER, metadata_json VARCHAR, "
            "members_json VARCHAR)"
        )
        db.execute(
            "CREATE TABLE score_observations (entity_id VARCHAR, kind VARCHAR, group_id VARCHAR, "
            "month VARCHAR, level DOUBLE, confidence DOUBLE, evolution DOUBLE, record_json VARCHAR)"
        )
        entities, observations = [], []
        for entity in payload["entities"].values():
            metadata = {k: v for k, v in entity.items() if k != "monthly"}
            metadata.setdefault("name", entity["id"])
            metadata["member_count"] = len(entity["members"])
            entities.append(
                (
                    entity["id"],
                    entity["kind"],
                    entity["group_id"],
                    metadata["name"],
                    entity["currency"],
                    len(entity["members"]),
                    json.dumps(metadata, allow_nan=False),
                    json.dumps(entity["members"]),
                )
            )
            for record in entity["monthly"]:
                scoring = record["scoring"]
                observations.append(
                    (
                        entity["id"],
                        entity["kind"],
                        entity["group_id"],
                        record["month"],
                        scoring["level"]["score"],
                        scoring["level"]["confidence"],
                        scoring["evolution"]["score"],
                        json.dumps(record, allow_nan=False),
                    )
                )
        if entities:
            db.executemany("INSERT INTO score_entities VALUES (?, ?, ?, ?, ?, ?, ?, ?)", entities)
        if observations:
            db.executemany(
                "INSERT INTO score_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)", observations
            )
        for table in ("score_entities", "score_observations"):
            path = str(output_dir / f"{table}.parquet").replace("'", "''")
            db.execute(f"COPY {table} TO '{path}' (FORMAT PARQUET)")
    profile = {
        "config": payload["score_config"],
        "provenance": provenance,
        "meta": payload.get("meta", {}),
        "fx_metadata": {
            k: v for k, v in payload.get("fx_metadata", {}).items() if k != "by_company"
        },
    }
    (output_dir / "score_profile.json").write_text(json.dumps(profile, indent=2), encoding="utf-8")


def read_entity(
    db: duckdb.DuckDBPyConnection,
    entity_id: str,
    cutoff: str | None = None,
    config: dict | None = None,
) -> dict | None:
    """Read one entity and its history through an optional inclusive month cutoff."""
    row = db.execute(
        "SELECT metadata_json FROM score_entities WHERE entity_id = ?", [entity_id]
    ).fetchone()
    if row is None:
        return None
    entity = json.loads(row[0])
    if cutoff and entity.get("debt_snapshot", {}).get("date", "")[:7] > cutoff[:7]:
        entity.pop("debt_snapshot")
    monthly = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT record_json FROM score_observations WHERE entity_id = ? "
            "AND (? IS NULL OR month <= ?) ORDER BY month",
            [entity_id, cutoff, cutoff],
        ).fetchall()
    ]
    members = []
    for member in entity["members"]:
        summary = db.execute(
            "SELECT e.entity_id, e.kind, e.group_id, e.name, o.level, o.confidence "
            "FROM score_entities e LEFT JOIN score_observations o "
            "ON e.entity_id = o.entity_id AND (? IS NULL OR o.month <= ?) "
            "WHERE e.entity_id = ? ORDER BY o.month DESC LIMIT 1",
            [cutoff, cutoff, member],
        ).fetchone()
        if summary:
            members.append(
                dict(
                    zip(
                        ("id", "kind", "group_id", "name", "level", "confidence"),
                        summary,
                        strict=True,
                    )
                )
            )
    return {"entity": entity, "monthly": monthly, "config": config or {}, "members": members}


def reweight_entity(detail: dict, weights: dict) -> dict:
    """Validate partial weight overrides and recompute without mutating stored records."""
    result = copy.deepcopy(detail)
    config = result["config"]
    for family, overrides in weights.items():
        if family not in config["weights"] or not isinstance(overrides, dict):
            raise ValueError(f"Unknown weight family: {family}")
        target = config["weights"][family]
        for name, value in overrides.items():
            if (
                name not in target
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid weight: {family}.{name}")
            target[name] = value
        if sum(target.values()) <= 0:
            raise ValueError(f"Choose at least one positive weight in {family}")
    entity = {**result["entity"], "monthly": result["monthly"]}
    for record, scoring in zip(result["monthly"], score_entity(entity, config), strict=True):
        record["scoring"] = scoring
    for member in result["members"]:
        member.pop("level", None)
        member.pop("confidence", None)
    return result


def main() -> None:
    """Build the isolated V3 serving directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROCESSED_DATA_DIR / "v3-serving")
    args = parser.parse_args()
    payload, provenance = load_payload()
    export_payload(payload, args.output_dir, provenance)
    print(f"Exported {len(payload['entities'])} entities to {args.output_dir}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def accepted_map_record(
    skill_root: Path,
    components: list[dict[str, Any]],
    *,
    map_id_override: str | None = None,
) -> dict[str, Any]:
    semantics = {
        "objective": "Provide a bounded structural authority for recorder tests.",
        "scope": ["focused evidence-bound recorder fixture"],
        "authority": ["test-owned component map"],
        "source_snapshot": [],
        "components": components,
    }
    map_id = "component-map-" + canonical_sha256(semantics)[:12]
    value: dict[str, Any] = {
        "schema_version": "1.0",
        "map_id": map_id_override or map_id,
        "map_state": "accepted",
        "created_at_utc": "2026-08-14T00:00:00Z",
        "accepted_at_utc": "2026-08-14T00:00:01Z",
        "origin_scan_id": "fixture-scan",
        "previous_map_id": None,
        "skill_name": "analyze-project-claims",
        "skill_sha256": hashlib.sha256((skill_root / "SKILL.md").read_bytes()).hexdigest(),
        "mapper_version": "1.2.0",
        **semantics,
    }
    value["integrity"] = {"canonical_payload_sha256": canonical_sha256(value)}
    return value

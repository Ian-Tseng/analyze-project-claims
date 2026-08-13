#!/usr/bin/env python3
"""Bootstrap, check, and explicitly accept versioned component-to-element maps."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
MAPPER_VERSION = "1.2.0"
TRANSIENT_PYTHON_SUFFIXES = {".pyc", ".pyo"}
CANDIDATE_STATES = {
    "bootstrapped_provisional",
    "drift_candidate",
    "conflict_candidate",
    "recovery_candidate",
}


class MapError(ValueError):
    """Raised when an observation or map violates the lifecycle contract."""


def _now() -> tuple[str, str]:
    value = datetime.now(timezone.utc)
    stamp = value.strftime("%Y%m%dT%H%M%S%fZ")
    return value.isoformat().replace("+00:00", "Z"), f"{stamp}-{uuid.uuid4().hex[:8]}"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_transient_python_artifact(root: Path, path: Path) -> bool:
    relative = path.relative_to(root)
    return "__pycache__" in relative.parts or path.suffix.lower() in (
        TRANSIENT_PYTHON_SUFFIXES
    )


def _add_integrity(record: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(record)
    result.pop("integrity", None)
    result["integrity"] = {
        "canonical_payload_sha256": _sha256_bytes(_canonical(result).encode("utf-8"))
    }
    return result


def _verify_integrity(record: dict[str, Any], location: str) -> None:
    integrity = record.get("integrity")
    if not isinstance(integrity, dict):
        raise MapError(f"{location} has no integrity object")
    expected = integrity.get("canonical_payload_sha256")
    if not isinstance(expected, str) or not expected:
        raise MapError(f"{location} has no canonical payload hash")
    payload = copy.deepcopy(record)
    payload.pop("integrity", None)
    observed = _sha256_bytes(_canonical(payload).encode("utf-8"))
    if observed != expected:
        raise MapError(f"{location} integrity mismatch")


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MapError(f"{field} must be a non-empty string")
    return value.strip()


def _require_text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MapError(f"{field} must be a list of strings")
    return [_require_text(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise MapError(f"{field} contains unsupported fields: {', '.join(unknown)}")


def _require_optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field)


def _require_sha256(value: Any, field: str) -> str:
    text = _require_text(value, field)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise MapError(f"{field} must be a lowercase SHA-256 hex digest")
    return text


def _require_map_id(value: Any, field: str) -> str:
    text = _require_text(value, field)
    if re.fullmatch(r"component-map-[0-9a-f]{12}", text) is None:
        raise MapError(f"{field} must match component-map-<12 lowercase hex characters>")
    return text


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MapError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MapError(f"{path} must contain a JSON object")
    return value


def _is_test_source(source: str) -> bool:
    normalized = source.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return "/tests/" in f"/{normalized}" or name.startswith("test_")


def _write_exclusive(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_atomic(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending-{uuid.uuid4().hex}")
    try:
        with pending.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, path)
    finally:
        if pending.exists():
            pending.unlink()


def _hash_declared_source(source: str, project_root: Path) -> dict[str, Any]:
    if "://" in source:
        return {"source": source, "exists": False, "kind": "external_uri", "sha256": None}
    declared = Path(source)
    root = project_root.resolve()
    if declared.is_absolute():
        resolved = declared.resolve(strict=False)
    else:
        resolved = (root / declared).resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise MapError(f"relative source escapes project root: {source}") from exc
    if not resolved.exists():
        return {"source": source, "exists": False, "kind": "missing", "sha256": None}
    if resolved.is_file():
        return {"source": source, "exists": True, "kind": "file", "sha256": _sha256_file(resolved)}
    if resolved.is_dir():
        entries: list[dict[str, str]] = []
        for child in sorted(
            path
            for path in resolved.rglob("*")
            if path.is_file() and not _is_transient_python_artifact(resolved, path)
        ):
            entries.append(
                {
                    "path": child.relative_to(resolved).as_posix(),
                    "sha256": _sha256_file(child),
                }
            )
        return {
            "source": source,
            "exists": True,
            "kind": "directory",
            "sha256": _sha256_bytes(_canonical(entries).encode("utf-8")),
        }
    return {"source": source, "exists": True, "kind": "other", "sha256": None}


def _normalize_observation(raw: dict[str, Any], project_root: Path) -> dict[str, Any]:
    _reject_unknown_keys(
        raw,
        {
            "objective",
            "scope",
            "authority",
            "components",
            "strongest_safe_claim",
            "claim_boundary",
            "unresolved_uncertainties",
        },
        "observation",
    )
    if "strongest_safe_claim" in raw:
        _require_text(raw["strongest_safe_claim"], "strongest_safe_claim")
    if "claim_boundary" in raw:
        _require_text(raw["claim_boundary"], "claim_boundary")
    if "unresolved_uncertainties" in raw:
        _require_text_list(raw["unresolved_uncertainties"], "unresolved_uncertainties")
    objective = _require_text(raw.get("objective"), "objective")
    scope = _require_text_list(raw.get("scope"), "scope")
    authority = _require_text_list(raw.get("authority"), "authority")
    raw_components = raw.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise MapError("components must be a non-empty list")

    component_ids: set[str] = set()
    components: list[dict[str, Any]] = []
    declared_sources = set(scope + authority)
    for component_index, raw_component in enumerate(raw_components):
        location = f"components[{component_index}]"
        if not isinstance(raw_component, dict):
            raise MapError(f"{location} must be an object")
        _reject_unknown_keys(
            raw_component,
            {"component_id", "component_type", "elements"},
            location,
        )
        component_id = _require_text(raw_component.get("component_id"), f"{location}.component_id")
        if component_id in component_ids:
            raise MapError(f"duplicate component_id: {component_id}")
        component_ids.add(component_id)
        component_type = _require_text(
            raw_component.get("component_type"), f"{location}.component_type"
        )
        raw_elements = raw_component.get("elements")
        if not isinstance(raw_elements, list) or not raw_elements:
            raise MapError(f"{location}.elements must be a non-empty list")
        element_ids: set[str] = set()
        elements: list[dict[str, Any]] = []
        for element_index, raw_element in enumerate(raw_elements):
            element_location = f"{location}.elements[{element_index}]"
            if not isinstance(raw_element, dict):
                raise MapError(f"{element_location} must be an object")
            if "evidence_locators" in raw_element:
                raise MapError(
                    f"{element_location}.evidence_locators is an output-map field; "
                    "use evidence for observation input"
                )
            _reject_unknown_keys(
                raw_element,
                {
                    "element_id",
                    "target",
                    "relation_type",
                    "method",
                    "check_status",
                    "claim_status",
                    "evidence",
                    "safe_interpretation",
                    "required_repair",
                },
                element_location,
            )
            optional_enums = {
                "method": {
                    "inspected",
                    "schema_validated",
                    "executed_test",
                    "replayed",
                    "inferred",
                    "not_tested",
                },
                "check_status": {"PASS", "FAIL", "PARTIAL", "PENDING", "NA", "BLOCKED"},
                "claim_status": {
                    "supported",
                    "partially_supported",
                    "contradicted",
                    "untested",
                    "invalidly_specified",
                    "not_applicable",
                },
            }
            for optional_field, allowed_values in optional_enums.items():
                if optional_field in raw_element:
                    observed_value = _require_text(
                        raw_element[optional_field],
                        f"{element_location}.{optional_field}",
                    )
                    if observed_value not in allowed_values:
                        raise MapError(
                            f"{element_location}.{optional_field} has unsupported value: "
                            f"{observed_value}"
                        )
            if "safe_interpretation" in raw_element:
                _require_text(
                    raw_element["safe_interpretation"],
                    f"{element_location}.safe_interpretation",
                )
            if "required_repair" in raw_element:
                _require_optional_text(
                    raw_element["required_repair"],
                    f"{element_location}.required_repair",
                )
            element_id = _require_text(raw_element.get("element_id"), f"{element_location}.element_id")
            if element_id in element_ids:
                raise MapError(f"{location} contains duplicate element_id: {element_id}")
            element_ids.add(element_id)
            target = _require_text(raw_element.get("target"), f"{element_location}.target")
            relation_type = raw_element.get("relation_type", "contains")
            relation_type = _require_text(relation_type, f"{element_location}.relation_type")
            evidence = raw_element.get("evidence", [])
            if (
                not isinstance(evidence, list)
                or not evidence
                or any(not isinstance(item, dict) for item in evidence)
            ):
                raise MapError(
                    f"{element_location}.evidence must be a non-empty list of objects"
                )
            locators: list[dict[str, str]] = []
            for evidence_index, item in enumerate(evidence):
                _reject_unknown_keys(
                    item,
                    {"source", "locator", "observed"},
                    f"{element_location}.evidence[{evidence_index}]",
                )
                source = _require_text(
                    item.get("source"), f"{element_location}.evidence[{evidence_index}].source"
                )
                locator = _require_text(
                    item.get("locator"), f"{element_location}.evidence[{evidence_index}].locator"
                )
                declared_sources.add(source)
                locators.append({"source": source, "locator": locator})
            if any(_is_test_source(item["source"]) for item in locators) and not any(
                not _is_test_source(item["source"]) for item in locators
            ):
                raise MapError(
                    f"{element_location}.evidence with test evidence must also name "
                    "a non-test dependency"
                )
            unique_locators = {
                (item["source"], item["locator"]): item for item in locators
            }
            elements.append(
                {
                    "element_id": element_id,
                    "target": target,
                    "relation_type": relation_type,
                    "evidence_locators": [
                        unique_locators[key] for key in sorted(unique_locators)
                    ],
                }
            )
        components.append(
            {
                "component_id": component_id,
                "component_type": component_type,
                "elements": sorted(elements, key=lambda item: item["element_id"]),
            }
        )

    snapshot = [
        _hash_declared_source(source, project_root) for source in sorted(declared_sources)
    ]
    return {
        "objective": objective,
        "scope": scope,
        "authority": authority,
        "source_snapshot": snapshot,
        "components": sorted(components, key=lambda item: item["component_id"]),
    }


def _map_semantics(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "objective": observation["objective"],
        "scope": observation["scope"],
        "authority": observation["authority"],
        "source_snapshot": observation["source_snapshot"],
        "components": observation["components"],
    }


def _build_map(
    observation: dict[str, Any],
    state: str,
    scan_id: str,
    recorded_at: str,
    skill_path: Path,
    previous_map_id: str | None,
) -> dict[str, Any]:
    semantics = _map_semantics(observation)
    map_id = f"component-map-{_sha256_bytes(_canonical(semantics).encode('utf-8'))[:12]}"
    return _add_integrity(
        {
            "schema_version": SCHEMA_VERSION,
            "map_id": map_id,
            "map_state": state,
            "created_at_utc": recorded_at,
            "accepted_at_utc": None,
            "origin_scan_id": scan_id,
            "previous_map_id": previous_map_id,
            "skill_name": "analyze-project-claims",
            "skill_sha256": _sha256_file(skill_path),
            "mapper_version": MAPPER_VERSION,
            **semantics,
        }
    )


def _validate_map(record: dict[str, Any], location: str) -> None:
    required_root = {
        "schema_version",
        "map_id",
        "map_state",
        "created_at_utc",
        "accepted_at_utc",
        "origin_scan_id",
        "previous_map_id",
        "skill_name",
        "skill_sha256",
        "mapper_version",
        "objective",
        "scope",
        "authority",
        "source_snapshot",
        "components",
        "integrity",
    }
    missing_root = sorted(required_root - set(record))
    if missing_root:
        raise MapError(f"{location} is missing required fields: {', '.join(missing_root)}")
    _reject_unknown_keys(record, required_root, location)

    integrity = record.get("integrity")
    if not isinstance(integrity, dict):
        raise MapError(f"{location}.integrity must be an object")
    _reject_unknown_keys(
        integrity, {"canonical_payload_sha256"}, f"{location}.integrity"
    )
    _require_sha256(
        integrity.get("canonical_payload_sha256"),
        f"{location}.integrity.canonical_payload_sha256",
    )
    _verify_integrity(record, location)

    if record.get("schema_version") != SCHEMA_VERSION:
        raise MapError(f"{location} has unsupported schema_version")
    map_id = _require_map_id(record.get("map_id"), f"{location}.map_id")
    state = _require_text(record.get("map_state"), f"{location}.map_state")
    if state not in CANDIDATE_STATES | {"accepted"}:
        raise MapError(f"{location} has unsupported map_state: {state}")
    _require_text(record.get("created_at_utc"), f"{location}.created_at_utc")
    accepted_at = _require_optional_text(
        record.get("accepted_at_utc"), f"{location}.accepted_at_utc"
    )
    if state == "accepted" and accepted_at is None:
        raise MapError(f"{location}.accepted_at_utc is required for accepted maps")
    if state in CANDIDATE_STATES and accepted_at is not None:
        raise MapError(f"{location}.accepted_at_utc must be null for candidates")
    _require_text(record.get("origin_scan_id"), f"{location}.origin_scan_id")
    previous_map_id = record.get("previous_map_id")
    if previous_map_id is not None:
        _require_map_id(previous_map_id, f"{location}.previous_map_id")
    if record.get("skill_name") != "analyze-project-claims":
        raise MapError(f"{location}.skill_name must be analyze-project-claims")
    _require_sha256(record.get("skill_sha256"), f"{location}.skill_sha256")
    _require_text(record.get("mapper_version"), f"{location}.mapper_version")
    _require_text(record.get("objective"), f"{location}.objective")
    _require_text_list(record.get("scope"), f"{location}.scope")
    _require_text_list(record.get("authority"), f"{location}.authority")

    source_snapshot = record.get("source_snapshot")
    if not isinstance(source_snapshot, list):
        raise MapError(f"{location}.source_snapshot must be a list")
    source_ids: set[str] = set()
    for source_index, source_item in enumerate(source_snapshot):
        source_location = f"{location}.source_snapshot[{source_index}]"
        if not isinstance(source_item, dict):
            raise MapError(f"{source_location} must be an object")
        required_source = {"source", "exists", "kind", "sha256"}
        missing_source = sorted(required_source - set(source_item))
        if missing_source:
            raise MapError(
                f"{source_location} is missing required fields: {', '.join(missing_source)}"
            )
        _reject_unknown_keys(source_item, required_source, source_location)
        source = _require_text(source_item.get("source"), f"{source_location}.source")
        if source in source_ids:
            raise MapError(f"{location} contains duplicate source: {source}")
        source_ids.add(source)
        if not isinstance(source_item.get("exists"), bool):
            raise MapError(f"{source_location}.exists must be a boolean")
        kind = _require_text(source_item.get("kind"), f"{source_location}.kind")
        if kind not in {"file", "directory", "missing", "external_uri", "other"}:
            raise MapError(f"{source_location}.kind is unsupported: {kind}")
        source_hash = source_item.get("sha256")
        if source_hash is not None:
            _require_sha256(source_hash, f"{source_location}.sha256")
        if kind in {"file", "directory"} and source_hash is None:
            raise MapError(f"{source_location}.sha256 is required for {kind}")

    components = record.get("components")
    if not isinstance(components, list) or not components:
        raise MapError(f"{location}.components must be a non-empty list")
    component_ids: set[str] = set()
    for component_index, component in enumerate(components):
        component_location = f"{location}.components[{component_index}]"
        if not isinstance(component, dict):
            raise MapError(f"{component_location} must be an object")
        required_component = {"component_id", "component_type", "elements"}
        missing_component = sorted(required_component - set(component))
        if missing_component:
            raise MapError(
                f"{component_location} is missing required fields: "
                f"{', '.join(missing_component)}"
            )
        _reject_unknown_keys(component, required_component, component_location)
        component_id = _require_text(
            component.get("component_id"), f"{component_location}.component_id"
        )
        if component_id in component_ids:
            raise MapError(f"{location} contains duplicate component_id: {component_id}")
        component_ids.add(component_id)
        _require_text(
            component.get("component_type"), f"{component_location}.component_type"
        )
        elements = component.get("elements")
        if not isinstance(elements, list) or not elements:
            raise MapError(f"{component_location}.elements must be a non-empty list")
        element_ids: set[str] = set()
        for element_index, element in enumerate(elements):
            element_location = f"{component_location}.elements[{element_index}]"
            if not isinstance(element, dict):
                raise MapError(f"{element_location} must be an object")
            required_element = {
                "element_id",
                "target",
                "relation_type",
                "evidence_locators",
            }
            missing_element = sorted(required_element - set(element))
            if missing_element:
                raise MapError(
                    f"{element_location} is missing required fields: "
                    f"{', '.join(missing_element)}"
                )
            _reject_unknown_keys(element, required_element, element_location)
            element_id = _require_text(
                element.get("element_id"), f"{element_location}.element_id"
            )
            if element_id in element_ids:
                raise MapError(
                    f"{component_location} contains duplicate element_id: {element_id}"
                )
            element_ids.add(element_id)
            _require_text(element.get("target"), f"{element_location}.target")
            _require_text(
                element.get("relation_type"), f"{element_location}.relation_type"
            )
            locators = element.get("evidence_locators")
            if not isinstance(locators, list):
                raise MapError(f"{element_location}.evidence_locators must be a list")
            seen_locators: set[tuple[str, str]] = set()
            for locator_index, locator in enumerate(locators):
                locator_location = (
                    f"{element_location}.evidence_locators[{locator_index}]"
                )
                if not isinstance(locator, dict):
                    raise MapError(f"{locator_location} must be an object")
                required_locator = {"source", "locator"}
                missing_locator = sorted(required_locator - set(locator))
                if missing_locator:
                    raise MapError(
                        f"{locator_location} is missing required fields: "
                        f"{', '.join(missing_locator)}"
                    )
                _reject_unknown_keys(locator, required_locator, locator_location)
                locator_key = (
                    _require_text(locator.get("source"), f"{locator_location}.source"),
                    _require_text(locator.get("locator"), f"{locator_location}.locator"),
                )
                if locator_key in seen_locators:
                    raise MapError(f"{element_location} contains duplicate evidence locator")
                seen_locators.add(locator_key)

    expected_map_id = (
        "component-map-"
        + _sha256_bytes(_canonical(_map_semantics(record)).encode("utf-8"))[:12]
    )
    if map_id != expected_map_id:
        raise MapError(
            f"{location}.map_id does not match its component-map semantic payload"
        )

def _flatten_components(record: dict[str, Any]) -> tuple[dict[str, str], dict[tuple[str, str], dict[str, Any]]]:
    component_types: dict[str, str] = {}
    elements: dict[tuple[str, str], dict[str, Any]] = {}
    for component in record["components"]:
        component_id = component["component_id"]
        component_types[component_id] = component["component_type"]
        for element in component["elements"]:
            elements[(component_id, element["element_id"])] = element
    return component_types, elements


def _compare_maps(accepted: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    before_components, before_elements = _flatten_components(accepted)
    after_components, after_elements = _flatten_components(observed)
    before_component_ids = set(before_components)
    after_component_ids = set(after_components)
    common_components = before_component_ids & after_component_ids
    changed_components = [
        {"component_id": component_id, "fields": ["component_type"]}
        for component_id in sorted(common_components)
        if before_components[component_id] != after_components[component_id]
    ]
    before_element_ids = set(before_elements)
    after_element_ids = set(after_elements)
    changed_elements: list[dict[str, Any]] = []
    for key in sorted(before_element_ids & after_element_ids):
        fields = [
            field
            for field in ("target", "relation_type", "evidence_locators")
            if before_elements[key].get(field) != after_elements[key].get(field)
        ]
        if fields:
            changed_elements.append(
                {"component_id": key[0], "element_id": key[1], "fields": fields}
            )

    before_sources = {item["source"]: item for item in accepted["source_snapshot"]}
    after_sources = {item["source"]: item for item in observed["source_snapshot"]}
    source_changes: list[dict[str, Any]] = []
    for source in sorted(set(before_sources) | set(after_sources)):
        before = before_sources.get(source)
        after = after_sources.get(source)
        if before != after:
            fields = sorted(
                field
                for field in {*(before or {}), *(after or {})}
                if (before or {}).get(field) != (after or {}).get(field)
            )
            source_changes.append({"source": source, "fields": fields})

    contract_changes = [
        field for field in ("objective", "scope", "authority") if accepted[field] != observed[field]
    ]
    return {
        "added_components": sorted(after_component_ids - before_component_ids),
        "removed_components": sorted(before_component_ids - after_component_ids),
        "changed_components": changed_components,
        "added_elements": [
            {"component_id": key[0], "element_id": key[1]}
            for key in sorted(after_element_ids - before_element_ids)
        ],
        "removed_elements": [
            {"component_id": key[0], "element_id": key[1]}
            for key in sorted(before_element_ids - after_element_ids)
        ],
        "changed_elements": changed_elements,
        "source_changes": source_changes,
        "contract_changes": contract_changes,
    }


def _has_changes(changes: dict[str, Any]) -> bool:
    return any(bool(value) for value in changes.values())


def _has_conflicts(changes: dict[str, Any]) -> bool:
    return bool(changes["changed_components"] or changes["changed_elements"])


def _relative_artifact(path: Path | None, map_root: Path) -> str | None:
    return path.relative_to(map_root).as_posix() if path is not None else None


def _history_event(
    *,
    event_id: str,
    recorded_at: str,
    action: str,
    before_state: str,
    after_state: str,
    accepted_map_id: str | None,
    candidate_map_id: str | None,
    changes: dict[str, Any],
    artifacts: dict[str, str | None],
    skill_path: Path,
) -> dict[str, Any]:
    return _add_integrity(
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "recorded_at_utc": recorded_at,
            "action": action,
            "map_state_before": before_state,
            "map_state_after": after_state,
            "accepted_map_id": accepted_map_id,
            "candidate_map_id": candidate_map_id,
            "changes": changes,
            "artifacts": artifacts,
            "skill_sha256": _sha256_file(skill_path),
            "mapper_version": MAPPER_VERSION,
        }
    )


def _write_history(map_root: Path, event_id: str, event: dict[str, Any]) -> Path:
    path = map_root / "scan-history" / f"{event_id}.json"
    _write_exclusive(path, event)
    return path


def _reconcile(args: argparse.Namespace, skill_path: Path) -> dict[str, Any]:
    observation_raw = _load_json(args.observation)
    observation = _normalize_observation(observation_raw, args.project_root)
    recorded_at, scan_id = _now()
    map_root = args.map_root.resolve()
    accepted_path = map_root / "accepted-map.json"
    empty_changes = {
        "added_components": [],
        "removed_components": [],
        "changed_components": [],
        "added_elements": [],
        "removed_elements": [],
        "changed_elements": [],
        "source_changes": [],
        "contract_changes": [],
    }

    if not accepted_path.exists():
        candidate = _build_map(
            observation,
            "bootstrapped_provisional",
            scan_id,
            recorded_at,
            skill_path,
            None,
        )
        candidate_path = map_root / "candidates" / f"{scan_id}-{candidate['map_id']}.json"
        _write_exclusive(candidate_path, candidate)
        event = _history_event(
            event_id=scan_id,
            recorded_at=recorded_at,
            action="bootstrapped_provisional",
            before_state="missing",
            after_state="bootstrapped_provisional",
            accepted_map_id=None,
            candidate_map_id=candidate["map_id"],
            changes=empty_changes,
            artifacts={
                "accepted_map": None,
                "candidate": _relative_artifact(candidate_path, map_root),
                "delta": None,
            },
            skill_path=skill_path,
        )
        history_path = _write_history(map_root, scan_id, event)
        return {
            "action": "bootstrapped_provisional",
            "accepted_map": None,
            "candidate": str(candidate_path.resolve()),
            "delta": None,
            "history": str(history_path.resolve()),
            "changes": empty_changes,
        }

    accepted = _load_json(accepted_path)
    try:
        _validate_map(accepted, "accepted-map.json")
        if accepted["map_state"] != "accepted":
            raise MapError("accepted-map.json does not have accepted state")
    except MapError as exc:
        candidate = _build_map(
            observation,
            "recovery_candidate",
            scan_id,
            recorded_at,
            skill_path,
            accepted.get("map_id") if isinstance(accepted.get("map_id"), str) else None,
        )
        candidate_path = map_root / "candidates" / f"{scan_id}-{candidate['map_id']}.json"
        _write_exclusive(candidate_path, candidate)
        changes = copy.deepcopy(empty_changes)
        changes["contract_changes"] = [f"accepted_map_invalid:{exc}"]
        event = _history_event(
            event_id=scan_id,
            recorded_at=recorded_at,
            action="accepted_map_invalid",
            before_state="invalid",
            after_state="recovery_candidate",
            accepted_map_id=accepted.get("map_id"),
            candidate_map_id=candidate["map_id"],
            changes=changes,
            artifacts={
                "accepted_map": "accepted-map.json",
                "candidate": _relative_artifact(candidate_path, map_root),
                "delta": None,
            },
            skill_path=skill_path,
        )
        history_path = _write_history(map_root, scan_id, event)
        return {
            "action": "accepted_map_invalid",
            "accepted_map": str(accepted_path.resolve()),
            "candidate": str(candidate_path.resolve()),
            "delta": None,
            "history": str(history_path.resolve()),
            "changes": changes,
        }

    observed_map = _build_map(
        observation,
        "drift_candidate",
        scan_id,
        recorded_at,
        skill_path,
        accepted["map_id"],
    )
    changes = _compare_maps(accepted, observed_map)
    if not _has_changes(changes):
        event = _history_event(
            event_id=scan_id,
            recorded_at=recorded_at,
            action="checked_unchanged",
            before_state="accepted",
            after_state="accepted",
            accepted_map_id=accepted["map_id"],
            candidate_map_id=None,
            changes=changes,
            artifacts={"accepted_map": "accepted-map.json", "candidate": None, "delta": None},
            skill_path=skill_path,
        )
        history_path = _write_history(map_root, scan_id, event)
        return {
            "action": "checked_unchanged",
            "accepted_map": str(accepted_path.resolve()),
            "candidate": None,
            "delta": None,
            "history": str(history_path.resolve()),
            "changes": changes,
        }

    action = "conflict_detected" if _has_conflicts(changes) else "drift_detected"
    observed_map["map_state"] = "conflict_candidate" if action == "conflict_detected" else "drift_candidate"
    observed_map = _add_integrity(observed_map)
    candidate_path = map_root / "candidates" / f"{scan_id}-{observed_map['map_id']}.json"
    _write_exclusive(candidate_path, observed_map)
    delta = _add_integrity(
        {
            "schema_version": SCHEMA_VERSION,
            "scan_id": scan_id,
            "recorded_at_utc": recorded_at,
            "action": action,
            "accepted_map_id": accepted["map_id"],
            "candidate_map_id": observed_map["map_id"],
            "changes": changes,
        }
    )
    delta_path = map_root / "deltas" / f"{scan_id}.json"
    _write_exclusive(delta_path, delta)
    event = _history_event(
        event_id=scan_id,
        recorded_at=recorded_at,
        action=action,
        before_state="accepted",
        after_state=observed_map["map_state"],
        accepted_map_id=accepted["map_id"],
        candidate_map_id=observed_map["map_id"],
        changes=changes,
        artifacts={
            "accepted_map": "accepted-map.json",
            "candidate": _relative_artifact(candidate_path, map_root),
            "delta": _relative_artifact(delta_path, map_root),
        },
        skill_path=skill_path,
    )
    history_path = _write_history(map_root, scan_id, event)
    return {
        "action": action,
        "accepted_map": str(accepted_path.resolve()),
        "candidate": str(candidate_path.resolve()),
        "delta": str(delta_path.resolve()),
        "history": str(history_path.resolve()),
        "changes": changes,
    }


def _accept(args: argparse.Namespace, skill_path: Path) -> dict[str, Any]:
    map_root = args.map_root.resolve()
    candidates_root = (map_root / "candidates").resolve()
    candidate_path = args.candidate.resolve()
    try:
        candidate_path.relative_to(candidates_root)
    except ValueError as exc:
        raise MapError("candidate must be inside map-root/candidates") from exc
    candidate = _load_json(candidate_path)
    _validate_map(candidate, str(candidate_path))
    current_skill_sha256 = _sha256_file(skill_path)
    if candidate["skill_sha256"] != current_skill_sha256:
        raise MapError("candidate skill_sha256 does not match the active SKILL.md")
    if candidate["mapper_version"] != MAPPER_VERSION:
        raise MapError("candidate mapper_version does not match the active mapper")
    if candidate["map_state"] not in CANDIDATE_STATES:
        raise MapError(f"candidate has non-promotable state: {candidate['map_state']}")

    recorded_at, event_id = _now()
    accepted_path = map_root / "accepted-map.json"
    archived_path: Path | None = None
    previous_map_id: str | None = None
    if accepted_path.exists():
        previous = _load_json(accepted_path)
        _validate_map(previous, "accepted-map.json")
        previous_map_id = previous["map_id"]
        archived_path = map_root / "accepted-history" / f"{event_id}-{previous_map_id}.json"
        _write_exclusive(archived_path, previous)

    accepted = copy.deepcopy(candidate)
    accepted["map_state"] = "accepted"
    accepted["accepted_at_utc"] = recorded_at
    accepted["previous_map_id"] = previous_map_id
    accepted = _add_integrity(accepted)
    _write_atomic(accepted_path, accepted)
    changes = {
        "accepted_candidate": candidate["map_id"],
        "archived_previous": previous_map_id,
    }
    event = _history_event(
        event_id=event_id,
        recorded_at=recorded_at,
        action="accepted_candidate",
        before_state="accepted" if previous_map_id else "missing",
        after_state="accepted",
        accepted_map_id=accepted["map_id"],
        candidate_map_id=candidate["map_id"],
        changes=changes,
        artifacts={
            "accepted_map": "accepted-map.json",
            "candidate": _relative_artifact(candidate_path, map_root),
            "archived_previous": _relative_artifact(archived_path, map_root),
        },
        skill_path=skill_path,
    )
    history_path = _write_history(map_root, event_id, event)
    return {
        "action": "accepted_candidate",
        "accepted_map": str(accepted_path.resolve()),
        "candidate": str(candidate_path),
        "archived_previous": str(archived_path.resolve()) if archived_path else None,
        "history": str(history_path.resolve()),
        "map_id": accepted["map_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    reconcile = subparsers.add_parser("reconcile", help="Bootstrap or check a component map")
    reconcile.add_argument("--observation", required=True, type=Path)
    reconcile.add_argument("--map-root", required=True, type=Path)
    reconcile.add_argument("--project-root", required=True, type=Path)

    accept = subparsers.add_parser("accept", help="Explicitly promote a validated candidate")
    accept.add_argument("--candidate", required=True, type=Path)
    accept.add_argument("--map-root", required=True, type=Path)

    args = parser.parse_args()
    skill_path = Path(__file__).resolve().parents[1] / "SKILL.md"
    try:
        output = _reconcile(args, skill_path) if args.command == "reconcile" else _accept(args, skill_path)
    except (MapError, OSError) as exc:
        print(f"reconcile_component_map: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

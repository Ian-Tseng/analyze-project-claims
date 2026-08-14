#!/usr/bin/env python3
"""Validate and append one analyze-project-claims scan record."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _internal.evidence_bound_scan import dispatch_if_v2


LOGGER_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"
METHODS = {
    "inspected",
    "schema_validated",
    "executed_test",
    "replayed",
    "inferred",
    "not_tested",
}
CHECK_STATUSES = {"PASS", "FAIL", "PARTIAL", "PENDING", "NA", "BLOCKED"}
CLAIM_STATUSES = {
    "supported",
    "partially_supported",
    "contradicted",
    "untested",
    "invalidly_specified",
    "not_applicable",
}


class RecordError(ValueError):
    """Raised when a proposed scan record violates the exchange contract."""


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{field} must be a non-empty string")
    return value.strip()


def _require_text_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RecordError(f"{field} must be a list of strings")
    return value


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RecordError(f"{field} has unknown fields: {', '.join(unknown)}")


def _derived_status(statuses: list[str]) -> str:
    if "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "PARTIAL" in statuses or "PENDING" in statuses:
        return "PARTIAL"
    if statuses and all(status == "NA" for status in statuses):
        return "NA"
    return "PASS"


def _normalize_element(raw: Any, location: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RecordError(f"{location} must be an object")
    _reject_unknown_keys(
        raw,
        {
            "element_id",
            "target",
            "method",
            "check_status",
            "claim_status",
            "evidence",
            "safe_interpretation",
            "required_repair",
        },
        location,
    )
    element_id = _require_text(raw.get("element_id"), f"{location}.element_id")
    target = _require_text(raw.get("target"), f"{location}.target")
    method = _require_text(raw.get("method"), f"{location}.method")
    if method not in METHODS:
        raise RecordError(f"{location}.method has unsupported method: {method}")
    check_status = _require_text(raw.get("check_status"), f"{location}.check_status")
    if check_status not in CHECK_STATUSES:
        raise RecordError(f"{location}.check_status is unsupported: {check_status}")
    claim_status = _require_text(raw.get("claim_status"), f"{location}.claim_status")
    if claim_status not in CLAIM_STATUSES:
        raise RecordError(f"{location}.claim_status is unsupported: {claim_status}")
    evidence = raw.get("evidence")
    if not isinstance(evidence, list) or any(not isinstance(item, dict) for item in evidence):
        raise RecordError(f"{location}.evidence must be a list of objects")
    for index, item in enumerate(evidence):
        _reject_unknown_keys(
            item,
            {"source", "locator", "observed"},
            f"{location}.evidence[{index}]",
        )
        _require_text(item.get("source"), f"{location}.evidence[{index}].source")
        _require_text(item.get("locator"), f"{location}.evidence[{index}].locator")
        if "observed" not in item:
            raise RecordError(f"{location}.evidence[{index}].observed is required")
    safe_interpretation = _require_text(
        raw.get("safe_interpretation"), f"{location}.safe_interpretation"
    )
    required_repair = raw.get("required_repair")
    if required_repair is not None and not isinstance(required_repair, str):
        raise RecordError(f"{location}.required_repair must be a string or null")
    return {
        "element_id": element_id,
        "target": target,
        "method": method,
        "check_status": check_status,
        "claim_status": claim_status,
        "evidence": evidence,
        "safe_interpretation": safe_interpretation,
        "required_repair": required_repair,
    }


def _normalize_record(raw: Any, skill_path: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RecordError("record must be a JSON object")
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
        "record",
    )
    objective = _require_text(raw.get("objective"), "objective")
    scope = _require_text_list(raw.get("scope"), "scope")
    authority = _require_text_list(raw.get("authority"), "authority")
    raw_components = raw.get("components")
    if not isinstance(raw_components, list) or not raw_components:
        raise RecordError("components must be a non-empty list")

    components: list[dict[str, Any]] = []
    component_ids: set[str] = set()
    all_statuses: list[str] = []
    for component_index, raw_component in enumerate(raw_components):
        location = f"components[{component_index}]"
        if not isinstance(raw_component, dict):
            raise RecordError(f"{location} must be an object")
        _reject_unknown_keys(
            raw_component,
            {"component_id", "component_type", "elements"},
            location,
        )
        component_id = _require_text(raw_component.get("component_id"), f"{location}.component_id")
        if component_id in component_ids:
            raise RecordError(f"duplicate component_id: {component_id}")
        component_ids.add(component_id)
        component_type = _require_text(
            raw_component.get("component_type"), f"{location}.component_type"
        )
        raw_elements = raw_component.get("elements")
        if not isinstance(raw_elements, list) or not raw_elements:
            raise RecordError(f"{location}.elements must be a non-empty list")
        elements = [
            _normalize_element(element, f"{location}.elements[{index}]")
            for index, element in enumerate(raw_elements)
        ]
        element_ids = [element["element_id"] for element in elements]
        if len(element_ids) != len(set(element_ids)):
            raise RecordError(f"{location} contains duplicate element_id values")
        statuses = [element["check_status"] for element in elements]
        all_statuses.extend(statuses)
        components.append(
            {
                "component_id": component_id,
                "component_type": component_type,
                "component_status": _derived_status(statuses),
                "element_counts": dict(sorted(Counter(statuses).items())),
                "elements": elements,
            }
        )

    now = datetime.now(timezone.utc)
    scan_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "scan": {
            "scan_id": scan_id,
            "recorded_at_utc": now.isoformat().replace("+00:00", "Z"),
            "skill_name": "analyze-project-claims",
            "skill_sha256": hashlib.sha256(skill_path.read_bytes()).hexdigest(),
            "logger_version": LOGGER_VERSION,
            "objective": objective,
            "scope": scope,
            "authority": authority,
        },
        "components": components,
        "summary": {
            "scan_status": _derived_status(all_statuses),
            "component_count": len(components),
            "element_count": len(all_statuses),
            "element_counts": dict(sorted(Counter(all_statuses).items())),
            "strongest_safe_claim": _require_text(
                raw.get("strongest_safe_claim"), "strongest_safe_claim"
            ),
            "claim_boundary": _require_text(raw.get("claim_boundary"), "claim_boundary"),
            "unresolved_uncertainties": _require_text_list(
                raw.get("unresolved_uncertainties"), "unresolved_uncertainties"
            ),
        },
    }
    canonical = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result["integrity"] = {
        "canonical_payload_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    }
    return result


def main() -> int:
    dispatched = dispatch_if_v2(sys.argv[1:])
    if dispatched is not None:
        return dispatched
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path, help="Input scan-record JSON")
    parser.add_argument("--log-dir", required=True, type=Path, help="Append-only history directory")
    args = parser.parse_args()

    skill_path = Path(__file__).resolve().parents[1] / "SKILL.md"
    try:
        raw = json.loads(args.record.read_text(encoding="utf-8"))
        normalized = _normalize_record(raw, skill_path)
        args.log_dir.mkdir(parents=True, exist_ok=True)
        output = args.log_dir / f"{normalized['scan']['scan_id']}.json"
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(normalized, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except (OSError, json.JSONDecodeError, RecordError) as exc:
        print(f"record_scan: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "log": str(output.resolve()),
                "scan_id": normalized["scan"]["scan_id"],
                "scan_status": normalized["summary"]["scan_status"],
                "component_count": normalized["summary"]["component_count"],
                "element_count": normalized["summary"]["element_count"],
                "canonical_payload_sha256": normalized["integrity"][
                    "canonical_payload_sha256"
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

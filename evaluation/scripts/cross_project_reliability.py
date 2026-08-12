#!/usr/bin/env python3
"""Prepare, collect, and audit the analyze-project-claims reliability study.

The bundled two-project run is a deterministic workflow fixture. It validates
the evaluation lifecycle and metric arithmetic; it is not empirical evidence
of cross-project reliability.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CONFIG_SCHEMA = "APC_CROSS_PROJECT_RELIABILITY_CONFIG_V1"
MANIFEST_SCHEMA = "APC_CROSS_PROJECT_RELIABILITY_MANIFEST_V1"
SUBMISSION_SCHEMA = "APC_CROSS_PROJECT_SUBMISSION_V1"
ADJUDICATION_SCHEMA = "APC_CROSS_PROJECT_ADJUDICATION_V1"
EXPECTED_CONDITIONS = {"agent_only", "generic_checklist", "skill_assisted"}
METRIC_FIELDS = (
    "finding_precision",
    "finding_recall",
    "finding_f1",
    "element_precision",
    "element_recall",
    "element_f1",
    "severe_finding_recall",
    "false_positive_element_rate",
    "repair_correct_rate",
    "provenance_preservation_rate",
    "elapsed_seconds",
    "input_tokens",
    "output_tokens",
)


class ContractError(RuntimeError):
    """Raised when an evaluation artifact violates the frozen contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON artifact must be an object: {path}")
    return value


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.pending")
    pending.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pending.replace(path)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _unique_ids(rows: list[dict[str, Any]], field: str, label: str) -> list[str]:
    values = [str(row.get(field, "")).strip() for row in rows]
    _require(all(values), f"every {label} requires non-empty {field}")
    _require(len(values) == len(set(values)), f"duplicate {label} {field}")
    return values


def _public_root(study_root: Path) -> Path:
    return study_root.resolve().parent


def _resolve_owned(study_root: Path, relative: str) -> Path:
    path = (study_root / relative).resolve()
    try:
        path.relative_to(_public_root(study_root))
    except ValueError as exc:
        raise ContractError(f"input path escapes the public kit: {relative}") from exc
    return path


def _iter_snapshot_files(root: Path) -> Iterable[Path]:
    _require(root.is_dir(), f"project snapshot directory is missing: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    _require(bool(files), f"project snapshot is empty: {root}")
    return files


def _resolved_input_hashes(config: dict[str, Any], study_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}

    def add_file(relative: str) -> None:
        path = _resolve_owned(study_root, relative)
        _require(path.is_file(), f"required input file is missing: {relative}")
        hashes[path.relative_to(_public_root(study_root)).as_posix()] = _file_sha256(path)

    for condition in config.get("conditions", []):
        add_file(str(condition.get("prompt_path", "")))
    for project in config.get("projects", []):
        snapshot = _resolve_owned(study_root, str(project.get("snapshot_root", "")))
        for path in _iter_snapshot_files(snapshot):
            hashes[path.relative_to(_public_root(study_root)).as_posix()] = _file_sha256(path)
        add_file(str(project.get("gold_labels", "")))
    fixture = config.get("fixture_plan")
    if isinstance(fixture, str) and fixture:
        add_file(fixture)
    skill_path = config.get("skill_path")
    if isinstance(skill_path, str) and skill_path:
        add_file(skill_path)
    return dict(sorted(hashes.items()))


def scientific_identity(config: dict[str, Any], study_root: Path) -> dict[str, Any]:
    frozen = copy.deepcopy(config)
    frozen.pop("runtime", None)
    return {
        "config": frozen,
        "resolved_input_sha256": _resolved_input_hashes(config, study_root),
    }


def scientific_config_hash(config: dict[str, Any], study_root: Path) -> str:
    return canonical_hash(scientific_identity(config, study_root))


def _load_gold(config: dict[str, Any], study_root: Path, project_id: str) -> dict[str, Any]:
    project = next((row for row in config["projects"] if row["id"] == project_id), None)
    _require(project is not None, f"unknown project: {project_id}")
    gold = _load_json(_resolve_owned(study_root, project["gold_labels"]))
    _require(gold.get("project_id") == project_id, f"gold project_id mismatch: {project_id}")
    elements = gold.get("element_inventory")
    findings = gold.get("gold_findings")
    _require(isinstance(elements, list) and elements, f"empty element inventory: {project_id}")
    _require(isinstance(findings, list), f"gold findings must be an array: {project_id}")
    element_ids = _unique_ids(elements, "element_id", f"{project_id} element")
    finding_ids = _unique_ids(findings, "gold_id", f"{project_id} gold finding")
    _require(len(finding_ids) == len(set(finding_ids)), f"duplicate gold IDs: {project_id}")
    for finding in findings:
        _require(
            finding.get("element_id") in element_ids,
            f"gold finding references unknown element: {project_id}/{finding.get('gold_id')}",
        )
        _require(
            finding.get("severity") in {"low", "moderate", "severe"},
            f"invalid severity: {project_id}/{finding.get('gold_id')}",
        )
    return gold


def validate_config(config: dict[str, Any], study_root: Path) -> None:
    _require(config.get("schema_version") == CONFIG_SCHEMA, "unsupported config schema")
    _require(bool(str(config.get("study_id", "")).strip()), "study_id is required")
    _require(bool(str(config.get("protocol_version", "")).strip()), "protocol_version is required")
    _require(config.get("paper_table_eligible") is False, "paper_table_eligible must be false")
    _require(
        config.get("general_reliability_proved") is False,
        "general_reliability_proved must be false before confirmatory evidence",
    )
    _require(config.get("analysis", {}).get("primary_unit") == "project", "primary unit must be project")

    conditions = config.get("conditions")
    projects = config.get("projects")
    families = config.get("agent_families")
    repeats = config.get("repeats")
    _require(isinstance(conditions, list), "conditions must be an array")
    _require(isinstance(projects, list), "projects must be an array")
    _require(isinstance(families, list), "agent_families must be an array")
    _require(isinstance(repeats, list), "repeats must be an array")
    condition_ids = set(_unique_ids(conditions, "id", "condition"))
    _require(condition_ids == EXPECTED_CONDITIONS, "the three comparison conditions are required")
    _require(len(_unique_ids(projects, "id", "project")) >= 2, "at least two projects are required")
    _require(
        len(_unique_ids(families, "id", "agent family")) >= 2,
        "at least two agent families are required",
    )
    _require(bool(_unique_ids(repeats, "id", "repeat")), "at least one repeat is required")

    phase = config.get("phase")
    scripted = [row["id"] for row in families if row.get("kind") == "scripted_fixture"]
    if phase == "confirmatory":
        _require(not scripted, "confirmatory evaluation cannot use a scripted fixture family")
        _require(
            config.get("labels", {}).get("independent_human_annotators", 0) >= 2,
            "confirmatory evaluation requires at least two independent human annotators",
        )
        _require(
            bool(config.get("preregistration", {}).get("frozen_identifier")),
            "confirmatory evaluation requires a frozen preregistration identifier",
        )
    elif phase == "workflow_dry_run":
        _require(
            config.get("execution_mode") == "deterministic_fixture_replay",
            "workflow dry run requires deterministic fixture replay",
        )
        _require(config.get("evidence_role") == "workflow_validation", "invalid dry-run evidence role")
        _require(bool(scripted), "workflow dry run requires scripted fixture families")
    elif phase != "development_pilot":
        raise ContractError(f"unsupported study phase: {phase}")

    for condition in conditions:
        prompt = _resolve_owned(study_root, condition["prompt_path"])
        _require(prompt.is_file() and prompt.stat().st_size > 0, f"missing prompt: {prompt}")
    for project in projects:
        list(_iter_snapshot_files(_resolve_owned(study_root, project["snapshot_root"])))
        _load_gold(config, study_root, project["id"])
    if phase == "workflow_dry_run":
        fixture = _resolve_owned(study_root, str(config.get("fixture_plan", "")))
        _require(fixture.is_file(), "fixture plan is missing")
    _resolved_input_hashes(config, study_root)


def _spec_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for project in config["projects"]:
        for condition in config["conditions"]:
            for family in config["agent_families"]:
                for repeat in config["repeats"]:
                    spec_id = "__".join((project["id"], condition["id"], family["id"], repeat["id"]))
                    rows.append(
                        {
                            "spec_id": spec_id,
                            "project_id": project["id"],
                            "condition_id": condition["id"],
                            "agent_family_id": family["id"],
                            "repeat_id": repeat["id"],
                            "status": "pending",
                            "attempts": 0,
                            "submission": f"submissions/{spec_id}.json",
                            "adjudication": f"adjudications/{spec_id}.json",
                            "completion_marker": f"controller/specs/{spec_id}.completed.json",
                        }
                    )
    return rows


def _copy_packets(config: dict[str, Any], study_root: Path, run_dir: Path) -> None:
    packet_root = run_dir / "packets"
    for project in config["projects"]:
        source = _resolve_owned(study_root, project["snapshot_root"])
        destination = packet_root / project["id"]
        for path in _iter_snapshot_files(source):
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        packet_manifest = {
            "schema_version": "APC_BLINDED_PROJECT_PACKET_V1",
            "project_id": project["id"],
            "gold_labels_included": False,
            "fixture_plan_included": False,
            "files": {
                path.relative_to(source).as_posix(): _file_sha256(path)
                for path in _iter_snapshot_files(source)
            },
        }
        _atomic_json(destination / "packet_manifest.json", packet_manifest)
    for condition in config["conditions"]:
        source = _resolve_owned(study_root, condition["prompt_path"])
        target = run_dir / "protocol" / "prompts" / f"{condition['id']}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def prepare_study(config_path: Path | str, output_root: Path | str) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    study_root = config_path.parent.parent
    config = _load_json(config_path)
    validate_config(config, study_root)
    identity = scientific_identity(config, study_root)
    config_hash = canonical_hash(identity)
    run_group_id = f"{config['study_id']}-{config_hash[:12]}"
    run_dir = Path(output_root).resolve() / run_group_id
    manifest_path = run_dir / "controller" / "manifest.json"
    if manifest_path.is_file():
        manifest = _load_json(manifest_path)
        _require(
            manifest.get("scientific_config_hash") == config_hash,
            "existing run directory has an incompatible scientific identity",
        )
        return {"run_dir": str(run_dir), "run_group_id": run_group_id, "scientific_config_hash": config_hash}

    run_dir.mkdir(parents=True, exist_ok=False)
    for relative in (
        "controller/specs",
        "protocol",
        "packets",
        "submissions",
        "adjudications",
        "review/gold",
        "summaries/conditions",
    ):
        (run_dir / relative).mkdir(parents=True, exist_ok=True)
    _copy_packets(config, study_root, run_dir)
    _atomic_json(run_dir / "protocol" / "frozen_config.json", config)
    _atomic_json(run_dir / "protocol" / "scientific_identity.json", identity)
    created_at = _now()
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "study_id": config["study_id"],
        "run_group_id": run_group_id,
        "scientific_config_hash": config_hash,
        "phase": config["phase"],
        "evidence_role": config["evidence_role"],
        "created_at": created_at,
        "source_root": str(study_root),
        "claim_boundary": config["claim_boundary"],
        "paper_table_eligible": False,
        "general_reliability_proved": False,
        "state": {
            "runner": "prepared",
            "audit": "not_run",
            "scientific": "untested",
            "acceptance": "not_eligible",
        },
        "paths": {
            "events": "controller/events.jsonl",
            "summary": "summaries/metrics.json",
            "artifact_manifest": "controller/artifact_manifest.json",
        },
        "runs": _spec_rows(config),
    }
    _atomic_json(manifest_path, manifest)
    _append_event(
        run_dir / "controller" / "events.jsonl",
        {
            "event": "study_prepared",
            "at": created_at,
            "run_group_id": run_group_id,
            "scientific_config_hash": config_hash,
            "spec_count": len(manifest["runs"]),
        },
    )
    return {"run_dir": str(run_dir), "run_group_id": run_group_id, "scientific_config_hash": config_hash}


def _spec_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["spec_id"]): row for row in rows}


def materialize_fixture_inputs(run_dir: Path | str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    manifest_path = run_dir / "controller" / "manifest.json"
    manifest = _load_json(manifest_path)
    source_root = Path(manifest["source_root"])
    config = _load_json(run_dir / "protocol" / "frozen_config.json")
    _require(
        config.get("execution_mode") == "deterministic_fixture_replay",
        "fixture materialization is allowed only for the workflow dry run",
    )
    plan = _load_json(_resolve_owned(source_root, config["fixture_plan"]))
    plans = plan.get("specs")
    _require(isinstance(plans, list), "fixture plan specs must be an array")
    plan_map = _spec_map(plans)
    expected = _spec_map(manifest["runs"])
    _require(set(plan_map) == set(expected), "fixture plan must cover every spec exactly once")
    created_at = _now()

    for spec_id, spec in expected.items():
        item = plan_map[spec_id]
        gold = _load_gold(config, source_root, spec["project_id"])
        gold_map = {row["gold_id"]: row for row in gold["gold_findings"]}
        element_ids = {row["element_id"] for row in gold["element_inventory"]}
        detected = item.get("detected_gold_ids", [])
        false_positives = item.get("false_positives", [])
        _require(isinstance(detected, list), f"invalid detected_gold_ids: {spec_id}")
        _require(isinstance(false_positives, list), f"invalid false_positives: {spec_id}")
        _require(set(detected).issubset(gold_map), f"fixture references unknown gold finding: {spec_id}")

        findings: list[dict[str, Any]] = []
        matches: list[dict[str, Any]] = []
        index = 1
        for gold_id in detected:
            gold_row = gold_map[gold_id]
            finding_id = f"finding-{index:02d}"
            findings.append(
                {
                    "finding_id": finding_id,
                    "element_id": gold_row["element_id"],
                    "summary": gold_row["summary"],
                    "evidence": gold_row["evidence"],
                    "proposed_repair": gold_row["required_repair"],
                }
            )
            matches.append(
                {
                    "finding_id": finding_id,
                    "gold_finding_id": gold_id,
                    "repair_correct": bool(item.get("repair_correct", True)),
                    "provenance_preserved": bool(item.get("provenance_preserved", True)),
                }
            )
            index += 1
        for false_positive in false_positives:
            element_id = false_positive["element_id"]
            _require(element_id in element_ids, f"fixture false positive uses unknown element: {spec_id}")
            finding_id = f"finding-{index:02d}"
            findings.append(
                {
                    "finding_id": finding_id,
                    "element_id": element_id,
                    "summary": false_positive["summary"],
                    "evidence": false_positive["evidence"],
                    "proposed_repair": false_positive["proposed_repair"],
                }
            )
            matches.append(
                {
                    "finding_id": finding_id,
                    "gold_finding_id": None,
                    "repair_correct": None,
                    "provenance_preserved": None,
                }
            )
            index += 1
        metadata = item.get("usage", {})
        submission = {
            "schema_version": SUBMISSION_SCHEMA,
            "spec_id": spec_id,
            "project_id": spec["project_id"],
            "condition_id": spec["condition_id"],
            "agent_family_id": spec["agent_family_id"],
            "repeat_id": spec["repeat_id"],
            "scientific_config_hash": manifest["scientific_config_hash"],
            "execution_kind": "scripted_fixture",
            "created_at": created_at,
            "elapsed_seconds": float(metadata.get("elapsed_seconds", 1.0)),
            "input_tokens": int(metadata.get("input_tokens", 100)),
            "output_tokens": int(metadata.get("output_tokens", 50)),
            "findings": findings,
        }
        adjudication = {
            "schema_version": ADJUDICATION_SCHEMA,
            "spec_id": spec_id,
            "scientific_config_hash": manifest["scientific_config_hash"],
            "reviewer_id": "scripted_fixture_not_human",
            "independent_human_review": False,
            "created_at": created_at,
            "matches": matches,
        }
        _atomic_json(run_dir / spec["submission"], submission)
        _atomic_json(run_dir / spec["adjudication"], adjudication)
        spec["status"] = "submitted"
        spec["attempts"] = 1
    manifest["state"]["runner"] = "submitted"
    manifest["updated_at"] = created_at
    _atomic_json(manifest_path, manifest)
    _append_event(
        run_dir / "controller" / "events.jsonl",
        {"event": "fixture_inputs_materialized", "at": created_at, "spec_count": len(expected)},
    )
    return {"run_dir": str(run_dir), "spec_count": len(expected)}


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return 0.0 if precision == 0 or recall == 0 else None
    return 2 * precision * recall / (precision + recall)


def _mean(values: Iterable[float | int | None]) -> float | None:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return None if not finite else sum(finite) / len(finite)


def _difference(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else left - right


def _validate_submission(spec: dict[str, Any], submission: dict[str, Any], config_hash: str) -> None:
    _require(submission.get("schema_version") == SUBMISSION_SCHEMA, f"invalid submission schema: {spec['spec_id']}")
    for field in ("spec_id", "project_id", "condition_id", "agent_family_id", "repeat_id"):
        _require(submission.get(field) == spec[field], f"submission {field} mismatch: {spec['spec_id']}")
    _require(
        submission.get("scientific_config_hash") == config_hash,
        f"submission config hash mismatch: {spec['spec_id']}",
    )
    findings = submission.get("findings")
    _require(isinstance(findings, list), f"submission findings must be an array: {spec['spec_id']}")
    _unique_ids(findings, "finding_id", f"{spec['spec_id']} finding") if findings else []
    for field in ("elapsed_seconds", "input_tokens", "output_tokens"):
        value = submission.get(field)
        _require(isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0, f"invalid {field}: {spec['spec_id']}")


def _validate_adjudication(
    spec: dict[str, Any], adjudication: dict[str, Any], submission: dict[str, Any], config_hash: str
) -> None:
    _require(adjudication.get("schema_version") == ADJUDICATION_SCHEMA, f"invalid adjudication schema: {spec['spec_id']}")
    _require(adjudication.get("spec_id") == spec["spec_id"], f"adjudication spec mismatch: {spec['spec_id']}")
    _require(
        adjudication.get("scientific_config_hash") == config_hash,
        f"adjudication config hash mismatch: {spec['spec_id']}",
    )
    matches = adjudication.get("matches")
    _require(isinstance(matches, list), f"adjudication matches must be an array: {spec['spec_id']}")
    submitted = {row["finding_id"] for row in submission["findings"]}
    reviewed = _unique_ids(matches, "finding_id", f"{spec['spec_id']} adjudication") if matches else []
    _require(set(reviewed) == submitted, f"every submitted finding must be adjudicated once: {spec['spec_id']}")


def _score_spec(
    spec: dict[str, Any], submission: dict[str, Any], adjudication: dict[str, Any], gold: dict[str, Any]
) -> dict[str, Any]:
    gold_map = {row["gold_id"]: row for row in gold["gold_findings"]}
    element_ids = {row["element_id"] for row in gold["element_inventory"]}
    gold_elements = {row["element_id"] for row in gold["gold_findings"]}
    non_gold_elements = element_ids - gold_elements
    findings = {row["finding_id"]: row for row in submission["findings"]}
    matches = {row["finding_id"]: row for row in adjudication["matches"]}
    for finding in findings.values():
        _require(
            finding.get("element_id") in element_ids,
            f"submission finding uses unknown element: {spec['spec_id']}/{finding.get('finding_id')}",
        )
    matched_gold: list[str] = []
    false_finding_ids: list[str] = []
    for finding_id, match in matches.items():
        gold_id = match.get("gold_finding_id")
        if gold_id is None:
            false_finding_ids.append(finding_id)
            continue
        _require(gold_id in gold_map, f"adjudication references unknown gold finding: {spec['spec_id']}")
        _require(gold_id not in matched_gold, f"duplicate match to one gold finding: {spec['spec_id']}/{gold_id}")
        matched_gold.append(gold_id)

    tp = len(matched_gold)
    fp = len(false_finding_ids)
    fn = len(gold_map) - tp
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    detected_elements = {gold_map[gold_id]["element_id"] for gold_id in matched_gold}
    predicted_elements = {row["element_id"] for row in findings.values()}
    fp_elements = predicted_elements & non_gold_elements
    element_tp = len(detected_elements)
    element_fp = len(fp_elements)
    element_fn = len(gold_elements - detected_elements)
    element_precision = _ratio(element_tp, element_tp + element_fp)
    element_recall = _ratio(element_tp, element_tp + element_fn)
    severe_gold = {key for key, row in gold_map.items() if row["severity"] == "severe"}
    matched_rows = [matches[finding_id] for finding_id in findings if matches[finding_id].get("gold_finding_id")]
    repair_values = [row.get("repair_correct") for row in matched_rows if isinstance(row.get("repair_correct"), bool)]
    provenance_values = [
        row.get("provenance_preserved")
        for row in matched_rows
        if isinstance(row.get("provenance_preserved"), bool)
    ]
    return {
        "spec_id": spec["spec_id"],
        "project_id": spec["project_id"],
        "condition_id": spec["condition_id"],
        "agent_family_id": spec["agent_family_id"],
        "repeat_id": spec["repeat_id"],
        "finding_counts": {"tp": tp, "fp": fp, "fn": fn},
        "element_counts": {"tp": element_tp, "fp": element_fp, "fn": element_fn},
        "finding_precision": precision,
        "finding_recall": recall,
        "finding_f1": _f1(precision, recall),
        "element_precision": element_precision,
        "element_recall": element_recall,
        "element_f1": _f1(element_precision, element_recall),
        "severe_finding_recall": _ratio(len(severe_gold & set(matched_gold)), len(severe_gold)),
        "false_positive_element_rate": _ratio(len(fp_elements), len(non_gold_elements)),
        "repair_correct_rate": _ratio(sum(repair_values), len(repair_values)),
        "provenance_preservation_rate": _ratio(sum(provenance_values), len(provenance_values)),
        "elapsed_seconds": float(submission["elapsed_seconds"]),
        "input_tokens": int(submission["input_tokens"]),
        "output_tokens": int(submission["output_tokens"]),
    }


def _alignment_hash(spec_results: list[dict[str, Any]]) -> str:
    keys = sorted(
        (row["project_id"], row["agent_family_id"], row["repeat_id"]) for row in spec_results
    )
    return canonical_hash(keys)


def _aggregate_conditions(spec_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregates: list[dict[str, Any]] = []
    for condition_id in sorted({row["condition_id"] for row in spec_results}):
        rows = [row for row in spec_results if row["condition_id"] == condition_id]
        aggregate: dict[str, Any] = {
            "condition_id": condition_id,
            "analysis_unit": "project_condition_family_repeat",
            "unit_count": len(rows),
            "project_count": len({row["project_id"] for row in rows}),
            "agent_family_count": len({row["agent_family_id"] for row in rows}),
            "alignment_hash": _alignment_hash(rows),
            "paper_table_eligible": False,
            "general_reliability_proved": False,
        }
        for field in METRIC_FIELDS:
            aggregate[f"macro_mean_{field}"] = _mean(row[field] for row in rows)
        aggregates.append(aggregate)
    return aggregates


def _comparison_deltas(spec_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (row["project_id"], row["agent_family_id"], row["repeat_id"], row["condition_id"]): row
        for row in spec_results
    }
    comparisons: list[dict[str, Any]] = []
    keys = sorted({key[:3] for key in by_key})
    for condition_id in sorted(EXPECTED_CONDITIONS - {"agent_only"}):
        rows = []
        for project_id, family_id, repeat_id in keys:
            baseline = by_key[(project_id, family_id, repeat_id, "agent_only")]
            treatment = by_key[(project_id, family_id, repeat_id, condition_id)]
            rows.append(
                {
                    "project_id": project_id,
                    "agent_family_id": family_id,
                    "repeat_id": repeat_id,
                    "finding_f1_delta": _difference(treatment["finding_f1"], baseline["finding_f1"]),
                    "severe_finding_recall_delta": _difference(
                        treatment["severe_finding_recall"],
                        baseline["severe_finding_recall"],
                    ),
                }
            )
        comparisons.append(
            {
                "condition_id": condition_id,
                "baseline_condition_id": "agent_only",
                "matched_project_unit_count": len(rows),
                "macro_mean_finding_f1_delta": _mean(row["finding_f1_delta"] for row in rows),
                "macro_mean_severe_finding_recall_delta": _mean(
                    row["severe_finding_recall_delta"] for row in rows
                ),
            }
        )
    return comparisons


def _compute_metrics(run_dir: Path, manifest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    source_root = Path(manifest["source_root"])
    spec_results: list[dict[str, Any]] = []
    for spec in manifest["runs"]:
        submission_path = run_dir / spec["submission"]
        adjudication_path = run_dir / spec["adjudication"]
        _require(submission_path.is_file(), f"missing submission: {spec['spec_id']}")
        _require(adjudication_path.is_file(), f"missing adjudication: {spec['spec_id']}")
        submission = _load_json(submission_path)
        adjudication = _load_json(adjudication_path)
        _validate_submission(spec, submission, manifest["scientific_config_hash"])
        _validate_adjudication(spec, adjudication, submission, manifest["scientific_config_hash"])
        gold_path = run_dir / "review" / "gold" / f"{spec['project_id']}.json"
        gold = _load_json(gold_path) if gold_path.is_file() else _load_gold(config, source_root, spec["project_id"])
        spec_results.append(_score_spec(spec, submission, adjudication, gold))
    return {
        "analysis_unit": "project_condition_family_repeat",
        "project_count": len({row["project_id"] for row in spec_results}),
        "condition_count": len({row["condition_id"] for row in spec_results}),
        "agent_family_count": len({row["agent_family_id"] for row in spec_results}),
        "repeat_count": len({row["repeat_id"] for row in spec_results}),
        "spec_results": sorted(spec_results, key=lambda row: row["spec_id"]),
        "condition_aggregates": _aggregate_conditions(spec_results),
        "matched_comparisons": _comparison_deltas(spec_results),
    }


def _copy_gold_after_submissions(config: dict[str, Any], source_root: Path, run_dir: Path) -> None:
    for project in config["projects"]:
        source = _resolve_owned(source_root, project["gold_labels"])
        target = run_dir / "review" / "gold" / f"{project['id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _project_relative(path: Path, config: dict[str, Any], source_root: Path) -> str:
    project_root_value = config.get("runtime", {}).get("project_root")
    if isinstance(project_root_value, str) and project_root_value:
        project_root = (source_root / project_root_value).resolve()
        try:
            return path.resolve().relative_to(project_root).as_posix()
        except ValueError:
            pass
    return path.resolve().as_posix()


def collect_study(run_dir: Path | str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    manifest_path = run_dir / "controller" / "manifest.json"
    manifest = _load_json(manifest_path)
    config = _load_json(run_dir / "protocol" / "frozen_config.json")
    source_root = Path(manifest["source_root"])

    # Fail before exposing gold labels if the execution grid is incomplete.
    for spec in manifest["runs"]:
        _require((run_dir / spec["submission"]).is_file(), f"missing submission: {spec['spec_id']}")
        _require((run_dir / spec["adjudication"]).is_file(), f"missing adjudication: {spec['spec_id']}")
    _copy_gold_after_submissions(config, source_root, run_dir)
    metrics = _compute_metrics(run_dir, manifest, config)
    summary = {
        "schema_version": "APC_CROSS_PROJECT_METRICS_V1",
        "study_id": manifest["study_id"],
        "run_group_id": manifest["run_group_id"],
        "scientific_config_hash": manifest["scientific_config_hash"],
        "phase": manifest["phase"],
        "evidence_role": manifest["evidence_role"],
        **metrics,
        "scientific_state": "untested",
        "acceptance_state": "not_eligible",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
        "claim_boundary": manifest["claim_boundary"],
    }
    _atomic_json(run_dir / "summaries" / "metrics.json", summary)
    for aggregate in summary["condition_aggregates"]:
        condition_summary = {
            "schema_version": "APC_CROSS_PROJECT_CONDITION_SUMMARY_V1",
            "run_group_id": manifest["run_group_id"],
            "scientific_config_hash": manifest["scientific_config_hash"],
            **aggregate,
        }
        _atomic_json(
            run_dir / "summaries" / "conditions" / f"{aggregate['condition_id']}.json",
            condition_summary,
        )

    completed_at = _now()
    for spec in manifest["runs"]:
        marker = {
            "schema_version": "APC_CROSS_PROJECT_SPEC_COMPLETE_V1",
            "spec_name": spec["spec_id"],
            "run_group_id": manifest["run_group_id"],
            "scientific_config_hash": manifest["scientific_config_hash"],
            "return_code": 0,
            "completed_step": "adjudicated_collection",
            "summary_path": "summaries/metrics.json",
            "completed_at": completed_at,
        }
        _atomic_json(run_dir / spec["completion_marker"], marker)
        spec["status"] = "complete"
    runner_marker = {
        "schema_version": "APC_CROSS_PROJECT_RUNNER_COMPLETE_V1",
        "runner_complete": True,
        "run_group_id": manifest["run_group_id"],
        "scientific_config_hash": manifest["scientific_config_hash"],
        "required_spec_count": len(manifest["runs"]),
        "completed_spec_count": len(manifest["runs"]),
        "completed_at": completed_at,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    _atomic_json(run_dir / "controller" / "runner_complete.json", runner_marker)
    manifest["state"]["runner"] = "complete"
    manifest["state"]["audit"] = "not_run"
    manifest["updated_at"] = completed_at
    _atomic_json(manifest_path, manifest)

    artifact_files: dict[str, str] = {}
    for path in sorted((run_dir / "summaries" / "conditions").glob("*.json")):
        artifact_files[_project_relative(path, config, source_root)] = _file_sha256(path)
    _atomic_json(run_dir / "controller" / "artifact_manifest.json", {"files": artifact_files})
    _append_event(
        run_dir / "controller" / "events.jsonl",
        {
            "event": "runner_completed",
            "at": completed_at,
            "spec_count": len(manifest["runs"]),
            "summary_sha256": _file_sha256(run_dir / "summaries" / "metrics.json"),
        },
    )
    return summary


def audit_study(run_dir: Path | str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    manifest_path = run_dir / "controller" / "manifest.json"
    manifest = _load_json(manifest_path)
    config = _load_json(run_dir / "protocol" / "frozen_config.json")
    summary_path = run_dir / "summaries" / "metrics.json"
    _require(summary_path.is_file(), "runner summary is missing")
    observed_summary = _load_json(summary_path)
    runner = _load_json(run_dir / "controller" / "runner_complete.json")
    _require(runner.get("runner_complete") is True, "runner completion marker is invalid")
    _require(
        runner.get("scientific_config_hash") == manifest["scientific_config_hash"],
        "runner completion hash mismatch",
    )
    for spec in manifest["runs"]:
        marker = _load_json(run_dir / spec["completion_marker"])
        _require(marker.get("return_code") == 0, f"spec marker return code failed: {spec['spec_id']}")
        _require(
            marker.get("scientific_config_hash") == manifest["scientific_config_hash"],
            f"spec marker config mismatch: {spec['spec_id']}",
        )
    replayed = _compute_metrics(run_dir, manifest, config)
    observed_core = {key: observed_summary.get(key) for key in replayed}
    _require(canonical_hash(observed_core) == canonical_hash(replayed), "metric replay mismatch")
    _require(observed_summary.get("paper_table_eligible") is False, "invalid paper-table flag")
    _require(observed_summary.get("general_reliability_proved") is False, "invalid reliability flag")

    audited_at = _now()
    audit_report = {
        "schema_version": "APC_CROSS_PROJECT_AUDIT_V1",
        "audit_passed": True,
        "audit_scope": "separately_invoked_deterministic_replay_same_implementation",
        "run_group_id": manifest["run_group_id"],
        "scientific_config_hash": manifest["scientific_config_hash"],
        "validated_spec_count": len(manifest["runs"]),
        "metrics_replayed": True,
        "label_packet_separation_validated": all(
            not (run_dir / "packets" / project["id"] / "gold.json").exists()
            for project in config["projects"]
        ),
        "scientific_state": "untested",
        "acceptance_state": "not_eligible",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
        "audited_at": audited_at,
    }
    _atomic_json(run_dir / "controller" / "audit_report.json", audit_report)
    audit_marker = {
        "schema_version": "APC_CROSS_PROJECT_AUDIT_COMPLETE_V1",
        "audit_complete": True,
        "audit_passed": True,
        "run_group_id": manifest["run_group_id"],
        "scientific_config_hash": manifest["scientific_config_hash"],
        "audit_report_sha256": _file_sha256(run_dir / "controller" / "audit_report.json"),
        "completed_at": audited_at,
    }
    _atomic_json(run_dir / "controller" / "audit_complete.json", audit_marker)
    completion = {
        "schema_version": "APC_CROSS_PROJECT_EXPERIMENT_COMPLETE_V1",
        "accepted_complete": True,
        "runner_complete": True,
        "audit_passed": True,
        "audit_complete": True,
        "run_group_id": manifest["run_group_id"],
        "scientific_config_hash": manifest["scientific_config_hash"],
        "evidence_role": manifest["evidence_role"],
        "scientific_state": "untested",
        "acceptance_state": "not_eligible",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
        "claim_boundary": manifest["claim_boundary"],
        "completed_at": audited_at,
    }
    _atomic_json(run_dir / "controller" / "experiment_complete.json", completion)
    manifest["state"]["audit"] = "passed"
    manifest["state"]["scientific"] = "untested"
    manifest["state"]["acceptance"] = "not_eligible"
    manifest["updated_at"] = audited_at
    _atomic_json(manifest_path, manifest)
    _append_event(
        run_dir / "controller" / "events.jsonl",
        {"event": "audit_completed", "at": audited_at, "audit_passed": True},
    )
    return audit_report


def run_dry_run(config_path: Path | str, output_root: Path | str) -> dict[str, Any]:
    prepared = prepare_study(config_path, output_root)
    run_dir = Path(prepared["run_dir"])
    completion_path = run_dir / "controller" / "experiment_complete.json"
    if completion_path.is_file():
        completion = _load_json(completion_path)
        _require(
            completion.get("scientific_config_hash") == prepared["scientific_config_hash"],
            "existing completion marker has an incompatible identity",
        )
        return {**prepared, "status": "complete", "reused_existing": True}
    materialize_fixture_inputs(run_dir)
    collect_study(run_dir)
    audit_study(run_dir)
    return {**prepared, "status": "complete", "reused_existing": False}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--config", required=True, type=Path)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--config", required=True, type=Path)
    prepare.add_argument("--output-root", required=True, type=Path)
    fixture = subparsers.add_parser("materialize-fixture")
    fixture.add_argument("--run-dir", required=True, type=Path)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--run-dir", required=True, type=Path)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--run-dir", required=True, type=Path)
    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--config", required=True, type=Path)
    dry_run.add_argument("--output-root", required=True, type=Path)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        if args.command == "preflight":
            config_path = args.config.resolve()
            study_root = config_path.parent.parent
            config = _load_json(config_path)
            validate_config(config, study_root)
            result = {
                "status": "preflight_passed",
                "scientific_config_hash": scientific_config_hash(config, study_root),
                "project_count": len(config["projects"]),
                "condition_count": len(config["conditions"]),
                "agent_family_count": len(config["agent_families"]),
                "paper_table_eligible": False,
                "general_reliability_proved": False,
            }
        elif args.command == "prepare":
            result = prepare_study(args.config, args.output_root)
        elif args.command == "materialize-fixture":
            result = materialize_fixture_inputs(args.run_dir)
        elif args.command == "collect":
            result = collect_study(args.run_dir)
        elif args.command == "audit":
            result = audit_study(args.run_dir)
        else:
            result = run_dry_run(args.config, args.output_root)
    except ContractError as exc:
        raise SystemExit(f"contract error: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

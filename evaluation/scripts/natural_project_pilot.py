#!/usr/bin/env python3
"""Freeze a natural-project sample and prepare blinded human-label packets.

This controller stops before agent execution. It establishes metadata-only
selection, source provenance, packet identity, and the manual gates that must
be satisfied before a development-pilot run can begin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SELECTION_SCHEMA = "APC_NATURAL_PROJECT_SELECTION_V1"
SOURCE_SCHEMA = "APC_PINNED_PROJECT_SOURCE_V1"
SELECTION_MANIFEST_SCHEMA = "APC_NATURAL_PROJECT_SELECTION_MANIFEST_V1"
PACKET_SCHEMA = "APC_BLINDED_ANNOTATION_PACKET_V1"
ANNOTATION_SCHEMA = "APC_INDEPENDENT_ANNOTATION_V1"
ADJUDICATED_GOLD_SCHEMA = "APC_BLINDED_ADJUDICATED_GOLD_V1"
LABEL_COMMITMENT_SCHEMA = "APC_NATURAL_PROJECT_LABEL_COMMITMENT_V1"
CALIBRATION_COMMITMENT_SCHEMA = "APC_ANNOTATION_CALIBRATION_COMMITMENT_V1"
CODEBOOK_COMMITMENT_SCHEMA = "APC_NATURAL_PROJECT_CODEBOOK_COMMITMENT_V1"
ALLOWED_LICENSES = {
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "MIT",
    "MPL-2.0",
    "Unlicense",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ContractError(RuntimeError):
    """Raised when pilot-selection or annotation preparation is unsafe."""


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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _unique(rows: list[dict[str, Any]], field: str, label: str) -> list[str]:
    values = [str(row.get(field, "")).strip() for row in rows]
    _require(all(values), f"every {label} requires non-empty {field}")
    _require(len(values) == len(set(values)), f"duplicate {label} {field}")
    return values


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def validate_snapshot_root(snapshot_root: Path | str, public_root: Path | str) -> Path:
    snapshot = Path(snapshot_root).resolve()
    public = Path(public_root).resolve()
    _require(
        not _is_within(snapshot, public),
        "natural project snapshots cannot be stored in the public bundle",
    )
    _require(snapshot.is_dir(), f"snapshot root is missing: {snapshot}")
    return snapshot


def validate_selection(selection: dict[str, Any]) -> dict[str, Any]:
    _require(selection.get("schema_version") == SELECTION_SCHEMA, "unsupported selection schema")
    _require(selection.get("phase") == "development_pilot", "selection phase must be development_pilot")
    _require(selection.get("evidence_role") == "development_evaluation", "invalid evidence role")
    _require(bool(str(selection.get("selection_id", "")).strip()), "selection_id is required")
    _require(bool(str(selection.get("claim_boundary", "")).strip()), "claim_boundary is required")
    _require(selection.get("paper_table_eligible") is False, "paper_table_eligible must be false")
    _require(
        selection.get("general_reliability_proved") is False,
        "general_reliability_proved must be false",
    )
    _require(
        selection.get("selection_frozen_before_outcome_review") is True,
        "selection must be frozen before outcome review",
    )

    sampling = selection.get("sampling_rule")
    _require(isinstance(sampling, dict), "sampling_rule must be an object")
    _require(sampling.get("outcome_fields_inspected") is False, "sampling inspected outcome fields")
    _require(bool(str(sampling.get("selection_basis", "")).strip()), "selection basis is required")
    _require(sampling.get("minimum_projects") == 4, "development minimum must be four projects")
    _require(sampling.get("maximum_projects") == 6, "development maximum must be six projects")

    projects = selection.get("projects")
    _require(isinstance(projects, list), "projects must be an array")
    _require(4 <= len(projects) <= 6, "development pilot requires 4-6 projects")
    _unique(projects, "id", "project")
    repository_urls = _unique(projects, "repository_url", "project")
    excluded = {str(value).rstrip("/") for value in selection.get("excluded_repositories", [])}
    _require(bool(excluded), "at least the originating repository must be excluded")

    for project in projects:
        project_id = project["id"]
        repository_url = str(project["repository_url"]).rstrip("/")
        _require(
            repository_url.startswith("https://github.com/") and repository_url.count("/") == 4,
            f"project repository must be a canonical GitHub URL: {project_id}",
        )
        _require(repository_url not in excluded, f"excluded repository selected: {project_id}")
        _require(COMMIT_RE.fullmatch(str(project.get("commit_sha", ""))) is not None, f"invalid commit_sha: {project_id}")
        _require(project.get("origin") == "natural_external", f"project is not natural_external: {project_id}")
        _require(project.get("outcome_known") is False, f"outcome_known must be false: {project_id}")
        _require(
            project.get("used_in_skill_development") is False,
            f"used_in_skill_development must be false: {project_id}",
        )
        _require(bool(str(project.get("primary_language", "")).strip()), f"missing language: {project_id}")
        _require(bool(str(project.get("task_stratum", "")).strip()), f"missing task stratum: {project_id}")
        _require(
            project.get("public_distribution", {}).get("include_source_snapshot") is False,
            f"natural source cannot enter the public bundle: {project_id}",
        )
        license_info = project.get("license")
        _require(isinstance(license_info, dict), f"missing license metadata: {project_id}")
        spdx_ids = license_info.get("spdx_ids")
        paths = license_info.get("file_paths")
        urls = license_info.get("evidence_urls")
        _require(isinstance(spdx_ids, list) and spdx_ids, f"missing SPDX license: {project_id}")
        _require(set(spdx_ids).issubset(ALLOWED_LICENSES), f"unapproved license: {project_id}")
        _require(isinstance(paths, list) and paths, f"missing license file path: {project_id}")
        _require(isinstance(urls, list) and len(urls) == len(paths), f"license evidence mismatch: {project_id}")
        _require(
            all(project["commit_sha"] in str(url) for url in urls),
            f"license evidence is not pinned to commit: {project_id}",
        )

    languages = {str(row["primary_language"]).casefold() for row in projects}
    strata = {str(row["task_stratum"]).casefold() for row in projects}
    _require(len(languages) >= 3, "pilot requires at least three language strata")
    _require(len(strata) >= 3, "pilot requires at least three task strata")

    slots = selection.get("annotator_slots")
    _require(isinstance(slots, list) and len(slots) >= 2, "two human annotator slots are required")
    _unique(slots, "id", "annotator slot")
    for slot in slots:
        _require(slot.get("kind") == "human", "annotator slots must be human")
        _require(slot.get("independent") is True, "annotators must be independent")
        _require(slot.get("condition_blinded") is True, "annotators must be condition blinded")

    limits = selection.get("packet_limits")
    _require(isinstance(limits, dict), "packet_limits must be an object")
    _require(int(limits.get("maximum_files_per_project", 0)) > 0, "invalid file limit")
    _require(int(limits.get("maximum_bytes_per_project", 0)) > 0, "invalid byte limit")
    return {
        "selection_id": selection["selection_id"],
        "selection_sha256": canonical_hash(selection),
        "project_count": len(projects),
        "language_count": len(languages),
        "task_stratum_count": len(strata),
        "repository_count": len(repository_urls),
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }


def _snapshot_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if ".git" in relative.parts or relative.as_posix() == ".apc-source.json":
            continue
        yield path


def _validate_project_snapshot(project: dict[str, Any], root: Path, limits: dict[str, Any]) -> dict[str, Any]:
    _require(root.is_dir(), f"project snapshot is missing: {project['id']}")
    provenance_path = root / ".apc-source.json"
    provenance = _load_json(provenance_path)
    _require(provenance.get("schema_version") == SOURCE_SCHEMA, f"invalid source schema: {project['id']}")
    expected_provenance = {
        "project_id": project["id"],
        "repository_url": project["repository_url"],
        "commit_sha": project["commit_sha"],
    }
    for field, expected in expected_provenance.items():
        _require(provenance.get(field) == expected, f"source {field} mismatch: {project['id']}")
    _require(project["commit_sha"] in str(provenance.get("archive_url", "")), f"archive is not commit-pinned: {project['id']}")
    _require(SHA256_RE.fullmatch(str(provenance.get("archive_sha256", ""))) is not None, f"invalid archive hash: {project['id']}")
    _require(bool(str(provenance.get("acquired_at", "")).strip()), f"missing acquisition timestamp: {project['id']}")

    declared_license_hashes = provenance.get("license_file_sha256")
    _require(isinstance(declared_license_hashes, dict), f"missing license hashes: {project['id']}")
    for relative in project["license"]["file_paths"]:
        license_path = (root / relative).resolve()
        _require(_is_within(license_path, root), f"license path escapes snapshot: {project['id']}")
        _require(license_path.is_file(), f"license file is missing: {project['id']}/{relative}")
        _require(
            declared_license_hashes.get(relative) == _file_sha256(license_path),
            f"license hash mismatch: {project['id']}/{relative}",
        )

    files = list(_snapshot_files(root))
    _require(bool(files), f"project snapshot is empty: {project['id']}")
    file_hashes = {path.relative_to(root).as_posix(): _file_sha256(path) for path in files}
    byte_count = sum(path.stat().st_size for path in files)
    _require(len(files) <= int(limits["maximum_files_per_project"]), f"snapshot file limit exceeded: {project['id']}")
    _require(byte_count <= int(limits["maximum_bytes_per_project"]), f"snapshot byte limit exceeded: {project['id']}")
    return {
        "project_id": project["id"],
        "repository_url": project["repository_url"],
        "commit_sha": project["commit_sha"],
        "archive_sha256": provenance["archive_sha256"],
        "file_count": len(files),
        "byte_count": byte_count,
        "files": file_hashes,
        "snapshot_sha256": canonical_hash(file_hashes),
    }


def _copy_project_snapshot(source: Path, destination: Path) -> None:
    for path in _snapshot_files(source):
        target = destination / "snapshot" / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def prepare_annotation_workspace(
    selection_path: Path | str,
    snapshot_root: Path | str,
    output_root: Path | str,
) -> dict[str, Any]:
    selection_path = Path(selection_path).resolve()
    selection = _load_json(selection_path)
    summary = validate_selection(selection)
    public_root = Path(__file__).resolve().parents[2]
    snapshots = validate_snapshot_root(snapshot_root, public_root)
    selection_hash = summary["selection_sha256"]
    run_group_id = f"{selection['selection_id']}-{selection_hash[:12]}"
    run_dir = Path(output_root).resolve() / run_group_id
    manifest_path = run_dir / "controller" / "selection_manifest.json"
    if manifest_path.is_file():
        manifest = _load_json(manifest_path)
        _require(manifest.get("selection_sha256") == selection_hash, "existing selection identity mismatch")
        return {
            "run_dir": str(run_dir),
            "run_group_id": run_group_id,
            "selection_sha256": selection_hash,
            "annotation_packet_count": manifest["annotation_packet_count"],
            "reused_existing": True,
            "paper_table_eligible": False,
            "general_reliability_proved": False,
        }

    pending = run_dir.with_name(f".{run_dir.name}.pending")
    _require(not run_dir.exists(), f"run directory exists without a valid manifest: {run_dir}")
    _require(not pending.exists(), f"pending preparation requires review: {pending}")
    (pending / "controller").mkdir(parents=True)
    (pending / "protocol").mkdir(parents=True)
    (pending / "review" / "raw_labels").mkdir(parents=True)
    (pending / "review" / "gold").mkdir(parents=True)
    _atomic_json(pending / "protocol" / "frozen_selection.json", selection)

    source_rows: list[dict[str, Any]] = []
    packet_count = 0
    for project in selection["projects"]:
        source_root = snapshots / project["id"]
        source_row = _validate_project_snapshot(project, source_root, selection["packet_limits"])
        source_rows.append(source_row)
        for slot in selection["annotator_slots"]:
            packet_root = pending / "annotation_packets" / slot["id"] / project["id"]
            _copy_project_snapshot(source_root, packet_root)
            packet_manifest = {
                "schema_version": PACKET_SCHEMA,
                "selection_sha256": selection_hash,
                "project_id": project["id"],
                "annotator_slot_id": slot["id"],
                "snapshot_sha256": source_row["snapshot_sha256"],
                "file_count": source_row["file_count"],
                "byte_count": source_row["byte_count"],
                "condition_prompts_included": False,
                "agent_outputs_included": False,
                "gold_labels_included": False,
                "other_annotator_labels_included": False,
            }
            _atomic_json(packet_root / "packet_manifest.json", packet_manifest)
            annotation_template = {
                "schema_version": ANNOTATION_SCHEMA,
                "selection_sha256": selection_hash,
                "project_id": project["id"],
                "annotator_slot_id": slot["id"],
                "snapshot_sha256": source_row["snapshot_sha256"],
                "annotator_id": "",
                "completed": False,
                "human_attestation": {
                    "human_annotator": False,
                    "independent": False,
                    "condition_blinded": False,
                    "no_agent_outputs_reviewed": False,
                    "attested_at": "",
                },
                "element_inventory": [],
                "candidate_findings": [],
                "notes": "",
            }
            _atomic_json(packet_root / "annotation.template.json", annotation_template)
            packet_count += 1

    source_manifest = {
        "schema_version": "APC_NATURAL_PROJECT_SOURCE_MANIFEST_V1",
        "selection_sha256": selection_hash,
        "authority": "source_of_truth",
        "lifecycle_class": "validated",
        "public_distribution_includes_source": False,
        "projects": source_rows,
    }
    _atomic_json(pending / "controller" / "source_manifest.json", source_manifest)
    created_at = _now()
    manifest = {
        "schema_version": SELECTION_MANIFEST_SCHEMA,
        "selection_id": selection["selection_id"],
        "run_group_id": run_group_id,
        "selection_sha256": selection_hash,
        "created_at": created_at,
        "selection_state": "frozen",
        "annotation_state": "pending_independent_human_labels",
        "agent_execution_state": "blocked",
        "scientific_state": "untested",
        "acceptance_state": "not_eligible",
        "project_count": len(selection["projects"]),
        "annotation_packet_count": packet_count,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
        "claim_boundary": selection["claim_boundary"],
    }
    _atomic_json(pending / "controller" / "selection_manifest.json", manifest)
    gate = {
        "schema_version": "APC_NATURAL_PROJECT_EXECUTION_GATE_V1",
        "execution_state": "blocked",
        "missing_gates": [
            "frozen_annotation_codebook",
            "independent_human_labels",
            "blinded_adjudicated_gold",
            "two_live_agent_families",
        ],
        "scientific_state": "untested",
        "acceptance_state": "not_eligible",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    _atomic_json(pending / "controller" / "execution_gate.json", gate)

    tracked = [
        pending / "controller" / "selection_manifest.json",
        pending / "controller" / "source_manifest.json",
        *sorted((pending / "annotation_packets").rglob("packet_manifest.json")),
    ]
    project_root = Path(__file__).resolve().parents[4]
    artifact_files: dict[str, str] = {}
    manifest_uses_project_root = True
    for path in tracked:
        relative = path.relative_to(pending)
        future_path = run_dir / relative
        try:
            key = future_path.relative_to(project_root).as_posix()
        except ValueError:
            manifest_uses_project_root = False
            key = relative.as_posix()
        artifact_files[key] = _file_sha256(path)
    _atomic_json(
        pending / "controller" / "monitor_artifact_manifest.json",
        {
            "files": dict(sorted(artifact_files.items())),
            "path_root": "project_root" if manifest_uses_project_root else "run_dir",
        },
    )
    pending.replace(run_dir)
    return {
        "run_dir": str(run_dir),
        "run_group_id": run_group_id,
        "selection_sha256": selection_hash,
        "annotation_packet_count": packet_count,
        "reused_existing": False,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }


def _nonempty_text(value: Any, label: str) -> str:
    text = str(value).strip()
    _require(bool(text), f"{label} must be non-empty")
    return text


def _validate_relative_path(value: Any, label: str) -> str:
    text = _nonempty_text(value, label).replace("\\", "/")
    path = Path(text)
    _require(not path.is_absolute() and ".." not in path.parts, f"{label} must be a safe relative path")
    return text


def _validate_element_inventory(rows: Any, label: str) -> set[str]:
    _require(isinstance(rows, list) and rows, f"{label} element_inventory must be non-empty")
    _require(all(isinstance(row, dict) for row in rows), f"{label} element_inventory rows must be objects")
    element_ids = set(_unique(rows, "element_id", f"{label} element"))
    methods = {"inspected", "schema_validated", "executed_test", "replayed", "inferred", "not_tested"}
    for row in rows:
        element_id = row["element_id"]
        _nonempty_text(row.get("component_id"), f"{label}/{element_id} component_id")
        _validate_relative_path(row.get("path"), f"{label}/{element_id} path")
        _nonempty_text(row.get("element_type"), f"{label}/{element_id} element_type")
        _require(
            row.get("observed_state") in methods,
            f"invalid observed_state: {label}/{element_id}",
        )
    return element_ids


def _validate_candidate_findings(rows: Any, element_ids: set[str], label: str) -> set[str]:
    _require(isinstance(rows, list), f"{label} candidate_findings must be an array")
    _require(all(isinstance(row, dict) for row in rows), f"{label} candidate findings must be objects")
    finding_ids = set(_unique(rows, "finding_id", f"{label} candidate finding")) if rows else set()
    classes = {
        "definition", "type_or_flow", "scope", "claim_evidence", "goal_metric",
        "lifecycle", "monitor", "document", "provenance",
    }
    claim_states = {"partially_supported", "contradicted", "untested", "invalidly_specified"}
    for row in rows:
        finding_id = row["finding_id"]
        _require(row.get("element_id") in element_ids, f"unknown finding element: {label}/{finding_id}")
        _require(row.get("inconsistency_class") in classes, f"invalid inconsistency class: {label}/{finding_id}")
        _require(row.get("claim_status") in claim_states, f"invalid claim status: {label}/{finding_id}")
        _require(row.get("severity") in {"low", "moderate", "severe"}, f"invalid severity: {label}/{finding_id}")
        conflicts = row.get("conflicting_element_ids")
        _require(
            isinstance(conflicts, list) and len(set(conflicts)) >= 2 and set(conflicts).issubset(element_ids),
            f"finding requires at least two known conflicting elements: {label}/{finding_id}",
        )
        evidence = row.get("evidence")
        _require(isinstance(evidence, list) and evidence, f"finding evidence is required: {label}/{finding_id}")
        for evidence_path in evidence:
            _validate_relative_path(evidence_path, f"{label}/{finding_id} evidence")
        counterevidence = row.get("counterevidence")
        _require(isinstance(counterevidence, list), f"finding counterevidence must be an array: {label}/{finding_id}")
        for evidence_path in counterevidence:
            _validate_relative_path(evidence_path, f"{label}/{finding_id} counterevidence")
        for field in ("why_conflict", "safest_interpretation", "required_repair"):
            _nonempty_text(row.get(field), f"{label}/{finding_id} {field}")
    return finding_ids


def _pilot_context(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _load_json(run_dir / "controller" / "selection_manifest.json")
    selection = _load_json(run_dir / "protocol" / "frozen_selection.json")
    selection_summary = validate_selection(selection)
    _require(
        manifest.get("selection_sha256") == selection_summary["selection_sha256"],
        "frozen selection identity mismatch",
    )
    source = _load_json(run_dir / "controller" / "source_manifest.json")
    _require(
        source.get("selection_sha256") == manifest["selection_sha256"],
        "source manifest selection identity mismatch",
    )
    return manifest, selection, source


def _collect_raw_annotations(
    run_dir: Path,
    manifest: dict[str, Any],
    selection: dict[str, Any],
    source: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, Any]]]:
    source_rows = {row["project_id"]: row for row in source.get("projects", [])}
    project_ids = [row["id"] for row in selection["projects"]]
    slot_ids = [row["id"] for row in selection["annotator_slots"]]
    _require(set(source_rows) == set(project_ids), "source manifest project coverage mismatch")
    raw_root = run_dir / "review" / "raw_labels"
    expected = {f"{slot_id}/{project_id}.json" for slot_id in slot_ids for project_id in project_ids}
    actual = {
        path.relative_to(raw_root).as_posix()
        for path in raw_root.rglob("*.json")
        if path.is_file()
    } if raw_root.is_dir() else set()
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    _require(not missing, f"missing independent annotation: {missing[0] if missing else ''}")
    _require(not extra, f"unexpected independent annotation: {extra[0] if extra else ''}")

    hashes: dict[str, str] = {}
    identities: dict[str, str] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    for slot_id in slot_ids:
        for project_id in project_ids:
            relative = f"{slot_id}/{project_id}.json"
            path = raw_root / relative
            artifact = _load_json(path)
            label = f"{slot_id}/{project_id}"
            _require(artifact.get("schema_version") == ANNOTATION_SCHEMA, f"invalid annotation schema: {label}")
            _require(artifact.get("selection_sha256") == manifest["selection_sha256"], f"annotation selection mismatch: {label}")
            _require(artifact.get("project_id") == project_id, f"annotation project mismatch: {label}")
            _require(artifact.get("annotator_slot_id") == slot_id, f"annotation slot mismatch: {label}")
            _require(
                artifact.get("snapshot_sha256") == source_rows[project_id]["snapshot_sha256"],
                f"annotation snapshot mismatch: {label}",
            )
            annotator_id = _nonempty_text(artifact.get("annotator_id"), f"{label} annotator_id")
            prior = identities.setdefault(slot_id, annotator_id)
            _require(prior == annotator_id, f"annotator identity changed within slot: {slot_id}")
            _require(artifact.get("completed") is True, f"annotation is not complete: {label}")
            attestation = artifact.get("human_attestation")
            _require(isinstance(attestation, dict), f"missing human attestation: {label}")
            for field in ("human_annotator", "independent", "condition_blinded", "no_agent_outputs_reviewed"):
                _require(attestation.get(field) is True, f"annotation attestation {field} is not true: {label}")
            _nonempty_text(attestation.get("attested_at"), f"{label} attested_at")
            element_ids = _validate_element_inventory(artifact.get("element_inventory"), label)
            _validate_candidate_findings(artifact.get("candidate_findings"), element_ids, label)
            hashes[relative] = _file_sha256(path)
            artifacts[relative] = artifact
    _require(len(set(identities.values())) == len(slot_ids), "annotator identities must be distinct across slots")
    return dict(sorted(hashes.items())), identities, artifacts


def _collect_adjudicated_gold(
    run_dir: Path,
    manifest: dict[str, Any],
    selection: dict[str, Any],
    source: dict[str, Any],
    raw_hashes: dict[str, str],
    annotator_ids: dict[str, str],
    raw_artifacts: dict[str, dict[str, Any]],
) -> tuple[dict[str, str], str]:
    source_rows = {row["project_id"]: row for row in source["projects"]}
    project_ids = [row["id"] for row in selection["projects"]]
    slot_ids = [row["id"] for row in selection["annotator_slots"]]
    gold_root = run_dir / "review" / "gold"
    expected = {f"{project_id}.json" for project_id in project_ids}
    actual = {path.name for path in gold_root.glob("*.json") if path.is_file()} if gold_root.is_dir() else set()
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    _require(not missing, f"missing blinded adjudicated gold: {missing[0] if missing else ''}")
    _require(not extra, f"unexpected adjudicated gold: {extra[0] if extra else ''}")

    hashes: dict[str, str] = {}
    adjudicator_id = ""
    for project_id in project_ids:
        path = gold_root / f"{project_id}.json"
        artifact = _load_json(path)
        _require(artifact.get("schema_version") == ADJUDICATED_GOLD_SCHEMA, f"invalid gold schema: {project_id}")
        _require(artifact.get("selection_sha256") == manifest["selection_sha256"], f"gold selection mismatch: {project_id}")
        _require(artifact.get("project_id") == project_id, f"gold project mismatch: {project_id}")
        _require(
            artifact.get("snapshot_sha256") == source_rows[project_id]["snapshot_sha256"],
            f"gold snapshot mismatch: {project_id}",
        )
        expected_sources = {slot_id: raw_hashes[f"{slot_id}/{project_id}.json"] for slot_id in slot_ids}
        _require(
            artifact.get("source_annotation_sha256") == expected_sources,
            f"gold source annotation hashes mismatch: {project_id}",
        )
        current_adjudicator = _nonempty_text(artifact.get("adjudicator_id"), f"{project_id} adjudicator_id")
        if adjudicator_id:
            _require(adjudicator_id == current_adjudicator, "adjudicator identity changed across projects")
        else:
            adjudicator_id = current_adjudicator
        _require(current_adjudicator not in set(annotator_ids.values()), "adjudicator must be independent of annotators")
        _require(artifact.get("gold_frozen") is True, f"gold_frozen is not true: {project_id}")
        attestation = artifact.get("adjudication_attestation")
        _require(isinstance(attestation, dict), f"missing adjudication attestation: {project_id}")
        for field in ("human_adjudicator", "independent_of_annotators", "condition_blinded", "no_agent_outputs_reviewed"):
            _require(attestation.get(field) is True, f"adjudication attestation {field} is not true: {project_id}")
        _nonempty_text(attestation.get("attested_at"), f"{project_id} adjudication attested_at")
        element_ids = _validate_element_inventory(artifact.get("element_inventory"), f"gold/{project_id}")
        findings = artifact.get("gold_findings")
        _require(isinstance(findings, list), f"gold_findings must be an array: {project_id}")
        _require(all(isinstance(row, dict) for row in findings), f"gold finding rows must be objects: {project_id}")
        if findings:
            _unique(findings, "gold_id", f"{project_id} gold finding")
        candidate_ids = {
            slot_id: {
                row["finding_id"]
                for row in raw_artifacts[f"{slot_id}/{project_id}.json"]["candidate_findings"]
            }
            for slot_id in slot_ids
        }
        for finding in findings:
            gold_id = finding["gold_id"]
            _require(finding.get("element_id") in element_ids, f"unknown gold element: {project_id}/{gold_id}")
            _require(finding.get("severity") in {"low", "moderate", "severe"}, f"invalid gold severity: {project_id}/{gold_id}")
            _require(
                finding.get("inconsistency_class") in {"definition", "type_or_flow", "scope", "claim_evidence", "goal_metric", "lifecycle", "monitor", "document", "provenance"},
                f"invalid gold inconsistency class: {project_id}/{gold_id}",
            )
            _require(finding.get("claim_status") in {"partially_supported", "contradicted", "untested", "invalidly_specified"}, f"invalid gold claim status: {project_id}/{gold_id}")
            for field in ("summary", "safest_interpretation", "required_repair"):
                _nonempty_text(finding.get(field), f"{project_id}/{gold_id} {field}")
            evidence = finding.get("evidence")
            _require(isinstance(evidence, list) and evidence, f"gold evidence is required: {project_id}/{gold_id}")
            for evidence_path in evidence:
                _validate_relative_path(evidence_path, f"{project_id}/{gold_id} evidence")
            sources = finding.get("source_candidate_finding_ids")
            _require(isinstance(sources, dict) and set(sources) == set(slot_ids), f"gold source candidate coverage mismatch: {project_id}/{gold_id}")
            _require(any(sources.values()), f"gold finding has no source candidate: {project_id}/{gold_id}")
            for slot_id, ids in sources.items():
                _require(isinstance(ids, list) and set(ids).issubset(candidate_ids[slot_id]), f"unknown source candidate: {project_id}/{gold_id}/{slot_id}")
        hashes[path.name] = _file_sha256(path)
    return dict(sorted(hashes.items())), adjudicator_id


def _calibration_set_material_from_commitment(
    commitment: dict[str, Any],
) -> dict[str, Any]:
    fields = (
        "calibration_run_group_id",
        "calibration_selection_sha256",
        "project_id",
        "snapshot_sha256",
        "codebook_initial_sha256",
        "codebook_final_sha256",
        "raw_label_sha256",
        "annotator_identity_sha256",
        "discussion_sha256",
    )
    return {field: commitment.get(field) for field in fields}


def _validate_external_calibration_commitment(
    calibration_run_dir: Path,
) -> tuple[dict[str, Any], Path, Path]:
    commitment_path = calibration_run_dir / "review" / "calibration_commitment.json"
    _require(commitment_path.is_file(), "completed calibration commitment is missing")
    commitment = _load_json(commitment_path)
    _require(
        commitment.get("schema_version") == CALIBRATION_COMMITMENT_SCHEMA,
        "invalid calibration commitment schema",
    )
    _require(commitment.get("commitment_state") == "frozen", "calibration commitment is not frozen")
    _require(commitment.get("calibration_completed") is True, "calibration is not complete")
    _require(commitment.get("evidence_role") == "training_only", "calibration evidence role is invalid")
    _require(
        commitment.get("reuse_in_development_or_confirmation_prohibited") is True,
        "calibration study-reuse prohibition is missing",
    )
    _require(commitment.get("paper_table_eligible") is False, "calibration paper flag must be false")
    _require(
        commitment.get("general_reliability_proved") is False,
        "calibration general-reliability flag must be false",
    )
    _nonempty_text(commitment.get("frozen_at"), "calibration commitment frozen_at")

    manifest = _load_json(calibration_run_dir / "controller" / "calibration_manifest.json")
    _require(
        manifest.get("run_group_id") == commitment.get("calibration_run_group_id"),
        "calibration run-group mismatch",
    )
    _require(
        manifest.get("selection_sha256") == commitment.get("calibration_selection_sha256"),
        "calibration selection mismatch",
    )
    source = _load_json(calibration_run_dir / "controller" / "source_manifest.json")
    source_rows = source.get("projects")
    _require(isinstance(source_rows, list) and len(source_rows) == 1, "calibration source coverage mismatch")
    _require(source_rows[0].get("project_id") == commitment.get("project_id"), "calibration project mismatch")
    _require(source_rows[0].get("snapshot_sha256") == commitment.get("snapshot_sha256"), "calibration snapshot mismatch")

    raw_hashes = commitment.get("raw_label_sha256")
    _require(isinstance(raw_hashes, dict) and len(raw_hashes) == 2, "calibration raw-label coverage mismatch")
    raw_root = calibration_run_dir / "review" / "raw_labels"
    actual = {
        path.relative_to(raw_root).as_posix()
        for path in raw_root.rglob("*.json")
        if path.is_file()
    } if raw_root.is_dir() else set()
    _require(actual == set(raw_hashes), "calibration raw-label file set mismatch")
    for relative, expected_hash in raw_hashes.items():
        safe_relative = _validate_relative_path(relative, "calibration raw-label path")
        path = (raw_root / safe_relative).resolve()
        _require(_is_within(path, raw_root), "calibration raw-label path escapes review root")
        _require(path.is_file() and _file_sha256(path) == expected_hash, f"calibration raw-label hash mismatch: {relative}")

    identity_hashes = commitment.get("annotator_identity_sha256")
    _require(isinstance(identity_hashes, dict) and len(identity_hashes) == 2, "calibration annotator identity coverage mismatch")
    _require(
        all(SHA256_RE.fullmatch(str(value)) is not None for value in identity_hashes.values()),
        "invalid calibration annotator identity hash",
    )
    discussion_path = calibration_run_dir / "review" / "calibration_discussion.json"
    _require(
        discussion_path.is_file()
        and _file_sha256(discussion_path) == commitment.get("discussion_sha256"),
        "calibration discussion hash mismatch",
    )
    discussion = _load_json(discussion_path)
    _require(discussion.get("status") == "complete", "calibration discussion is not complete")
    _require(
        discussion.get("selection_sha256") == commitment.get("calibration_selection_sha256"),
        "calibration discussion selection mismatch",
    )
    _require(
        discussion.get("independent_annotation_sha256") == raw_hashes,
        "calibration discussion raw-label hashes mismatch",
    )
    _require(
        discussion.get("codebook_final_sha256") == commitment.get("codebook_final_sha256"),
        "calibration discussion final-codebook mismatch",
    )
    final_codebook = calibration_run_dir / "protocol" / "final-annotation-codebook.md"
    _require(
        final_codebook.is_file()
        and _file_sha256(final_codebook) == commitment.get("codebook_final_sha256"),
        "calibration final-codebook hash mismatch",
    )
    material = _calibration_set_material_from_commitment(commitment)
    _require(
        commitment.get("calibration_set_sha256") == canonical_hash(material),
        "calibration set identity mismatch",
    )
    return commitment, commitment_path, final_codebook


def _copy_bound_artifact(source: Path, destination: Path) -> None:
    if destination.is_file():
        _require(
            _file_sha256(destination) == _file_sha256(source),
            f"existing bound artifact identity mismatch: {destination.name}",
        )
        return
    pending = destination.with_name(f".{destination.name}.pending")
    _require(not pending.exists(), f"pending bound artifact requires review: {pending}")
    shutil.copy2(source, pending)
    pending.replace(destination)


def _study_codebook_material(
    manifest: dict[str, Any],
    calibration_commitment: dict[str, Any],
    calibration_commitment_sha256: str,
) -> dict[str, Any]:
    return {
        "run_group_id": manifest["run_group_id"],
        "selection_sha256": manifest["selection_sha256"],
        "calibration_run_group_id": calibration_commitment["calibration_run_group_id"],
        "calibration_selection_sha256": calibration_commitment["calibration_selection_sha256"],
        "calibration_set_sha256": calibration_commitment["calibration_set_sha256"],
        "calibration_commitment_sha256": calibration_commitment_sha256,
        "annotation_codebook_sha256": calibration_commitment["codebook_final_sha256"],
    }


def _validate_codebook_commitment(run_dir: Path) -> dict[str, Any]:
    manifest, _, _ = _pilot_context(run_dir)
    binding_path = run_dir / "protocol" / "codebook_commitment.json"
    _require(binding_path.is_file(), "frozen annotation codebook commitment is missing")
    binding = _load_json(binding_path)
    _require(
        binding.get("schema_version") == CODEBOOK_COMMITMENT_SCHEMA,
        "unsupported annotation codebook commitment schema",
    )
    copied_calibration_path = run_dir / "protocol" / "calibration_commitment.json"
    frozen_codebook = run_dir / "protocol" / "frozen-annotation-codebook.md"
    _require(copied_calibration_path.is_file(), "bound calibration commitment is missing")
    _require(frozen_codebook.is_file(), "frozen annotation codebook is missing")
    _require(
        _file_sha256(copied_calibration_path) == binding.get("calibration_commitment_sha256"),
        "bound calibration commitment hash mismatch",
    )
    calibration_commitment = _load_json(copied_calibration_path)
    _require(
        calibration_commitment.get("schema_version") == CALIBRATION_COMMITMENT_SCHEMA,
        "bound calibration commitment schema mismatch",
    )
    _require(
        calibration_commitment.get("commitment_state") == "frozen"
        and calibration_commitment.get("calibration_completed") is True,
        "bound calibration commitment is incomplete",
    )
    _require(
        calibration_commitment.get("evidence_role") == "training_only"
        and calibration_commitment.get("reuse_in_development_or_confirmation_prohibited") is True,
        "bound calibration evidence boundary mismatch",
    )
    calibration_material = _calibration_set_material_from_commitment(calibration_commitment)
    _require(
        calibration_commitment.get("calibration_set_sha256") == canonical_hash(calibration_material),
        "bound calibration set identity mismatch",
    )
    _require(
        _file_sha256(frozen_codebook) == binding.get("annotation_codebook_sha256"),
        "frozen annotation codebook hash mismatch",
    )
    expected_material = _study_codebook_material(
        manifest, calibration_commitment, _file_sha256(copied_calibration_path)
    )
    expected = {
        "binding_state": "frozen",
        "calibration_completed": True,
        "calibration_evidence_role": "training_only",
        "calibration_evidence_excluded_from_study": True,
        **expected_material,
        "study_codebook_binding_sha256": canonical_hash(expected_material),
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    for field, value in expected.items():
        _require(binding.get(field) == value, f"annotation codebook commitment mismatch: {field}")
    _nonempty_text(binding.get("bound_at"), "annotation codebook commitment bound_at")
    return binding


def bind_codebook(
    run_dir: Path | str,
    calibration_run_dir: Path | str,
) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    calibration_run_dir = Path(calibration_run_dir).resolve()
    manifest, _, _ = _pilot_context(run_dir)
    raw_root = run_dir / "review" / "raw_labels"
    gold_root = run_dir / "review" / "gold"
    _require(not any(raw_root.rglob("*.json")), "cannot bind codebook after development labels exist")
    _require(not any(gold_root.rglob("*.json")), "cannot bind codebook after development gold exists")
    _require(
        not (run_dir / "review" / "label_commitment.json").exists(),
        "cannot bind codebook after label commitment exists",
    )
    calibration, calibration_path, final_codebook = _validate_external_calibration_commitment(
        calibration_run_dir
    )
    copied_calibration = run_dir / "protocol" / "calibration_commitment.json"
    frozen_codebook = run_dir / "protocol" / "frozen-annotation-codebook.md"
    binding_path = run_dir / "protocol" / "codebook_commitment.json"
    if binding_path.is_file():
        binding = _validate_codebook_commitment(run_dir)
        _require(
            binding["calibration_commitment_sha256"] == _file_sha256(calibration_path),
            "supplied calibration differs from frozen study binding",
        )
        return {**binding, "commitment_path": str(binding_path), "reused_existing": True}

    _copy_bound_artifact(calibration_path, copied_calibration)
    _copy_bound_artifact(final_codebook, frozen_codebook)
    material = _study_codebook_material(
        manifest, calibration, _file_sha256(copied_calibration)
    )
    binding = {
        "schema_version": CODEBOOK_COMMITMENT_SCHEMA,
        "binding_state": "frozen",
        "calibration_completed": True,
        "calibration_evidence_role": "training_only",
        "calibration_evidence_excluded_from_study": True,
        **material,
        "study_codebook_binding_sha256": canonical_hash(material),
        "bound_at": _now(),
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    _atomic_json(binding_path, binding)
    _validate_codebook_commitment(run_dir)
    gate = execution_gate_status(run_dir)
    _atomic_json(run_dir / "controller" / "execution_gate.json", gate)
    return {**binding, "commitment_path": str(binding_path), "reused_existing": False}

def _label_set_material(
    manifest: dict[str, Any],
    source: dict[str, Any],
    raw_hashes: dict[str, str],
    gold_hashes: dict[str, str],
    annotator_ids: dict[str, str],
    adjudicator_id: str,
    codebook_binding: dict[str, Any],
) -> dict[str, Any]:
    return {
        "selection_sha256": manifest["selection_sha256"],
        "annotation_codebook_sha256": codebook_binding["annotation_codebook_sha256"],
        "calibration_set_sha256": codebook_binding["calibration_set_sha256"],
        "study_codebook_binding_sha256": codebook_binding["study_codebook_binding_sha256"],
        "source_snapshot_sha256": {
            row["project_id"]: row["snapshot_sha256"] for row in source["projects"]
        },
        "raw_label_sha256": raw_hashes,
        "adjudicated_gold_sha256": gold_hashes,
        "annotator_identity_sha256": {
            slot_id: hashlib.sha256(identity.encode("utf-8")).hexdigest()
            for slot_id, identity in sorted(annotator_ids.items())
        },
        "adjudicator_identity_sha256": hashlib.sha256(adjudicator_id.encode("utf-8")).hexdigest(),
    }


def label_preflight(run_dir: Path | str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    manifest, selection, source = _pilot_context(run_dir)
    codebook_binding = _validate_codebook_commitment(run_dir)
    raw_hashes, annotator_ids, _ = _collect_raw_annotations(run_dir, manifest, selection, source)
    slot_ids = [row["id"] for row in selection["annotator_slots"]]
    return {
        "schema_version": "APC_NATURAL_PROJECT_LABEL_PREFLIGHT_V1",
        "run_group_id": manifest["run_group_id"],
        "selection_sha256": manifest["selection_sha256"],
        "annotation_count": len(raw_hashes),
        "independent_human_annotators": len(set(annotator_ids.values())),
        "annotation_codebook_sha256": codebook_binding["annotation_codebook_sha256"],
        "calibration_set_sha256": codebook_binding["calibration_set_sha256"],
        "study_codebook_binding_sha256": codebook_binding["study_codebook_binding_sha256"],
        "raw_label_sha256": raw_hashes,
        "adjudication_inputs": [
            {
                "project_id": project["id"],
                "source_annotation_sha256": {
                    slot_id: raw_hashes[f"{slot_id}/{project['id']}.json"] for slot_id in slot_ids
                },
                "gold_output": f"review/gold/{project['id']}.json",
            }
            for project in selection["projects"]
        ],
        "status": "independent_labels_validated_pending_blinded_adjudication",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }


def _validate_label_commitment(run_dir: Path, commitment: dict[str, Any]) -> None:
    manifest, selection, source = _pilot_context(run_dir)
    codebook_binding = _validate_codebook_commitment(run_dir)
    _require(commitment.get("schema_version") == LABEL_COMMITMENT_SCHEMA, "unsupported label commitment schema")
    raw_hashes, annotator_ids, raw_artifacts = _collect_raw_annotations(run_dir, manifest, selection, source)
    gold_hashes, adjudicator_id = _collect_adjudicated_gold(
        run_dir, manifest, selection, source, raw_hashes, annotator_ids, raw_artifacts
    )
    material = _label_set_material(manifest, source, raw_hashes, gold_hashes, annotator_ids, adjudicator_id, codebook_binding)
    expected = {
        "run_group_id": manifest["run_group_id"],
        "selection_sha256": manifest["selection_sha256"],
        "commitment_state": "frozen",
        "condition_blinded": True,
        "gold_frozen": True,
        "independent_human_annotators": len(annotator_ids),
        "adjudicator_count": 1,
        "annotation_count": len(raw_hashes),
        "project_count": len(selection["projects"]),
        **material,
        "label_set_sha256": canonical_hash(material),
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    for field, value in expected.items():
        _require(commitment.get(field) == value, f"label commitment mismatch: {field}")
    _nonempty_text(commitment.get("frozen_at"), "label commitment frozen_at")


def freeze_labels(run_dir: Path | str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    manifest, selection, source = _pilot_context(run_dir)
    codebook_binding = _validate_codebook_commitment(run_dir)
    commitment_path = run_dir / "review" / "label_commitment.json"
    if commitment_path.is_file():
        commitment = _load_json(commitment_path)
        _validate_label_commitment(run_dir, commitment)
        return {**commitment, "commitment_path": str(commitment_path), "reused_existing": True}

    raw_hashes, annotator_ids, raw_artifacts = _collect_raw_annotations(run_dir, manifest, selection, source)
    gold_hashes, adjudicator_id = _collect_adjudicated_gold(
        run_dir, manifest, selection, source, raw_hashes, annotator_ids, raw_artifacts
    )
    material = _label_set_material(manifest, source, raw_hashes, gold_hashes, annotator_ids, adjudicator_id, codebook_binding)
    commitment = {
        "schema_version": LABEL_COMMITMENT_SCHEMA,
        "run_group_id": manifest["run_group_id"],
        "selection_sha256": manifest["selection_sha256"],
        "commitment_state": "frozen",
        "condition_blinded": True,
        "gold_frozen": True,
        "independent_human_annotators": len(annotator_ids),
        "adjudicator_count": 1,
        "annotation_count": len(raw_hashes),
        "project_count": len(selection["projects"]),
        **material,
        "label_set_sha256": canonical_hash(material),
        "frozen_at": _now(),
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    _atomic_json(commitment_path, commitment)
    _validate_label_commitment(run_dir, _load_json(commitment_path))
    gate = execution_gate_status(run_dir)
    _atomic_json(run_dir / "controller" / "execution_gate.json", gate)
    return {**commitment, "commitment_path": str(commitment_path), "reused_existing": False}
def execution_gate_status(run_dir: Path | str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    manifest = _load_json(run_dir / "controller" / "selection_manifest.json")
    missing: list[str] = []
    invalid_gate_reasons: list[str] = []
    codebook_commitment_path = run_dir / "protocol" / "codebook_commitment.json"
    if not codebook_commitment_path.is_file():
        missing.append("frozen_annotation_codebook")
    else:
        try:
            _validate_codebook_commitment(run_dir)
        except ContractError as exc:
            missing.extend(("frozen_annotation_codebook", "invalid_codebook_commitment"))
            invalid_gate_reasons.append(str(exc))

    label_commitment_path = run_dir / "review" / "label_commitment.json"
    if not label_commitment_path.is_file():
        missing.extend(("independent_human_labels", "blinded_adjudicated_gold"))
    else:
        commitment = _load_json(label_commitment_path)
        try:
            _validate_label_commitment(run_dir, commitment)
        except ContractError as exc:
            missing.extend(("independent_human_labels", "blinded_adjudicated_gold", "invalid_label_commitment"))
            invalid_gate_reasons.append(str(exc))

    agent_path = run_dir / "protocol" / "live_agent_config.json"
    if not agent_path.is_file():
        missing.append("two_live_agent_families")
    else:
        agents = _load_json(agent_path).get("agent_families")
        if not (
            isinstance(agents, list)
            and len({row.get("id") for row in agents if row.get("kind") == "live_agent" and row.get("version")}) >= 2
            and all(row.get("kind") != "scripted_fixture" for row in agents)
        ):
            missing.append("two_live_agent_families")

    return {
        "schema_version": "APC_NATURAL_PROJECT_EXECUTION_GATE_V1",
        "run_group_id": manifest["run_group_id"],
        "selection_sha256": manifest["selection_sha256"],
        "execution_state": "ready" if not missing else "blocked",
        "missing_gates": sorted(set(missing)),
        "invalid_gate_reasons": invalid_gate_reasons,
        "scientific_state": "untested",
        "acceptance_state": "not_eligible",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--selection", required=True, type=Path)
    prepare = commands.add_parser("prepare-annotations")
    prepare.add_argument("--selection", required=True, type=Path)
    prepare.add_argument("--snapshot-root", required=True, type=Path)
    prepare.add_argument("--output-root", required=True, type=Path)
    bind = commands.add_parser("bind-codebook")
    bind.add_argument("--run-dir", required=True, type=Path)
    bind.add_argument("--calibration-run-dir", required=True, type=Path)
    gate = commands.add_parser("gate")
    gate.add_argument("--run-dir", required=True, type=Path)
    label_check = commands.add_parser("label-preflight")
    label_check.add_argument("--run-dir", required=True, type=Path)
    freeze = commands.add_parser("freeze-labels")
    freeze.add_argument("--run-dir", required=True, type=Path)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        if args.command == "preflight":
            result = validate_selection(_load_json(args.selection.resolve()))
            result["status"] = "selection_preflight_passed"
        elif args.command == "prepare-annotations":
            result = prepare_annotation_workspace(args.selection, args.snapshot_root, args.output_root)
        elif args.command == "bind-codebook":
            result = bind_codebook(args.run_dir, args.calibration_run_dir)
        elif args.command == "gate":
            result = execution_gate_status(args.run_dir)
        elif args.command == "label-preflight":
            result = label_preflight(args.run_dir)
        else:
            result = freeze_labels(args.run_dir)
    except ContractError as exc:
        raise SystemExit(f"contract error: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()







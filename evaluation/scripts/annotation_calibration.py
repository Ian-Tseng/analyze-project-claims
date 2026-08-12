#!/usr/bin/env python3
"""Prepare a non-study natural-project exercise for human codebook calibration.

Calibration labels are training material for the annotators and codebook only.
They are permanently excluded from development, confirmation, paper tables,
and general-reliability claims. This controller never creates human labels or
an agent-execution gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from natural_project_pilot import (
    ALLOWED_LICENSES,
    COMMIT_RE,
    ContractError,
    SOURCE_SCHEMA,
    _atomic_json,
    _copy_project_snapshot,
    _file_sha256,
    _is_within,
    _load_json,
    _nonempty_text,
    _now,
    _require,
    _unique,
    _validate_candidate_findings,
    _validate_element_inventory,
    _validate_project_snapshot,
    canonical_hash,
    validate_snapshot_root,
)


CALIBRATION_SELECTION_SCHEMA = "APC_ANNOTATION_CALIBRATION_SELECTION_V1"
CALIBRATION_MANIFEST_SCHEMA = "APC_ANNOTATION_CALIBRATION_MANIFEST_V1"
CALIBRATION_PACKET_SCHEMA = "APC_ANNOTATION_CALIBRATION_PACKET_V1"
CALIBRATION_DISCUSSION_SCHEMA = "APC_ANNOTATION_CALIBRATION_DISCUSSION_V1"
CALIBRATION_COMMITMENT_SCHEMA = "APC_ANNOTATION_CALIBRATION_COMMITMENT_V1"
ANNOTATION_SCHEMA = "APC_INDEPENDENT_ANNOTATION_V1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_EXCLUDED_SELECTION_ID = "apc-natural-development-pilot-v1"
FROZEN_DEVELOPMENT_SELECTION_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "natural-development-pilot.selection.json"
)


def _frozen_development_repositories() -> set[str]:
    development = _load_json(FROZEN_DEVELOPMENT_SELECTION_PATH)
    _require(
        development.get("selection_id") == REQUIRED_EXCLUDED_SELECTION_ID,
        "frozen development selection identity mismatch",
    )
    projects = development.get("projects")
    _require(isinstance(projects, list) and projects, "frozen development selection has no projects")
    return {str(row.get("repository_url", "")).rstrip("/") for row in projects}


def validate_calibration_selection(selection: dict[str, Any]) -> dict[str, Any]:
    """Validate the fail-closed boundary around a one-project practice set."""

    _require(
        selection.get("schema_version") == CALIBRATION_SELECTION_SCHEMA,
        "unsupported calibration selection schema",
    )
    _require(selection.get("phase") == "annotation_calibration", "invalid calibration phase")
    _require(selection.get("evidence_role") == "training_only", "invalid evidence role")
    _require(bool(str(selection.get("selection_id", "")).strip()), "selection_id is required")
    _require(bool(str(selection.get("claim_boundary", "")).strip()), "claim_boundary is required")
    _require(selection.get("paper_table_eligible") is False, "paper_table_eligible must be false")
    _require(
        selection.get("general_reliability_proved") is False,
        "general_reliability_proved must be false",
    )
    _require(
        selection.get("reuse_in_development_or_confirmation_prohibited") is True,
        "reuse in development or confirmation must be prohibited",
    )
    excluded_ids = selection.get("excluded_study_selection_ids")
    _require(isinstance(excluded_ids, list), "excluded_study_selection_ids must be an array")
    _require(
        REQUIRED_EXCLUDED_SELECTION_ID in excluded_ids,
        "frozen development selection must be explicitly excluded",
    )

    codebook = selection.get("codebook")
    _require(isinstance(codebook, dict), "codebook identity is required")
    _require(bool(str(codebook.get("path", "")).strip()), "codebook path is required")
    _require(
        SHA256_RE.fullmatch(str(codebook.get("sha256", ""))) is not None,
        "invalid codebook SHA-256",
    )

    limits = selection.get("packet_limits")
    _require(isinstance(limits, dict), "packet_limits must be an object")
    _require(int(limits.get("maximum_files_per_project", 0)) > 0, "invalid file limit")
    _require(int(limits.get("maximum_bytes_per_project", 0)) > 0, "invalid byte limit")

    slots = selection.get("annotator_slots")
    _require(isinstance(slots, list) and len(slots) == 2, "exactly two calibration annotators are required")
    _unique(slots, "id", "calibration annotator slot")
    for slot in slots:
        _require(slot.get("kind") == "human", "calibration annotators must be human")
        _require(
            slot.get("independent_first_pass") is True,
            "calibration requires independent first passes",
        )
        _require(slot.get("condition_blinded") is True, "calibration annotators must be condition blinded")

    project = selection.get("project")
    _require(isinstance(project, dict), "exactly one calibration project is required")
    project_id = str(project.get("id", "")).strip()
    _require(bool(project_id), "calibration project id is required")
    repository_url = str(project.get("repository_url", "")).rstrip("/")
    _require(
        repository_url.startswith("https://github.com/") and repository_url.count("/") == 4,
        "calibration project must use a canonical GitHub URL",
    )
    _require(
        repository_url not in _frozen_development_repositories(),
        "calibration project overlaps the frozen development pilot",
    )
    _require(COMMIT_RE.fullmatch(str(project.get("commit_sha", ""))) is not None, "invalid commit_sha")
    _require(project.get("origin") == "natural_external", "calibration project is not natural_external")
    _require(bool(str(project.get("primary_language", "")).strip()), "missing primary language")
    _require(bool(str(project.get("task_stratum", "")).strip()), "missing task stratum")
    _require(
        project.get("public_distribution", {}).get("include_source_snapshot") is False,
        "calibration source cannot enter the public bundle",
    )
    license_info = project.get("license")
    _require(isinstance(license_info, dict), "missing license metadata")
    spdx_ids = license_info.get("spdx_ids")
    paths = license_info.get("file_paths")
    urls = license_info.get("evidence_urls")
    _require(isinstance(spdx_ids, list) and spdx_ids, "missing SPDX license")
    _require(set(spdx_ids).issubset(ALLOWED_LICENSES), "unapproved license")
    _require(isinstance(paths, list) and paths, "missing license file path")
    _require(isinstance(urls, list) and len(urls) == len(paths), "license evidence mismatch")
    _require(
        all(project["commit_sha"] in str(url) for url in urls),
        "license evidence is not pinned to commit",
    )

    return {
        "selection_id": selection["selection_id"],
        "selection_sha256": canonical_hash(selection),
        "project_count": 1,
        "annotator_count": 2,
        "calibration_only": True,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }


def _validate_codebook(selection: dict[str, Any], codebook_path: Path | str) -> Path:
    path = Path(codebook_path).resolve()
    _require(path.is_file(), f"codebook is missing: {path}")
    _require(
        _file_sha256(path) == selection["codebook"]["sha256"],
        "codebook SHA-256 mismatch",
    )
    return path


def prepare_calibration_workspace(
    selection_path: Path | str,
    snapshot_root: Path | str,
    output_root: Path | str,
    codebook_path: Path | str,
) -> dict[str, Any]:
    """Prepare immutable practice packets without creating scientific evidence."""

    selection_path = Path(selection_path).resolve()
    selection = _load_json(selection_path)
    summary = validate_calibration_selection(selection)
    codebook = _validate_codebook(selection, codebook_path)
    public_root = Path(__file__).resolve().parents[2]
    snapshots = validate_snapshot_root(snapshot_root, public_root)
    selection_hash = summary["selection_sha256"]
    run_group_id = f"{selection['selection_id']}-{selection_hash[:12]}"
    run_dir = Path(output_root).resolve() / run_group_id
    manifest_path = run_dir / "controller" / "calibration_manifest.json"
    if manifest_path.is_file():
        manifest = _load_json(manifest_path)
        _require(manifest.get("selection_sha256") == selection_hash, "existing calibration identity mismatch")
        _require(manifest.get("codebook_sha256") == _file_sha256(codebook), "existing codebook identity mismatch")
        return {
            "run_dir": str(run_dir),
            "run_group_id": run_group_id,
            "selection_sha256": selection_hash,
            "annotation_packet_count": manifest["annotation_packet_count"],
            "calibration_state": manifest["calibration_state"],
            "reused_existing": True,
            "paper_table_eligible": False,
            "general_reliability_proved": False,
        }

    pending = run_dir.with_name(f".{run_dir.name}.pending")
    _require(not run_dir.exists(), f"run directory exists without a valid manifest: {run_dir}")
    _require(not pending.exists(), f"pending calibration preparation requires review: {pending}")
    (pending / "controller").mkdir(parents=True)
    (pending / "protocol").mkdir(parents=True)
    (pending / "review" / "raw_labels").mkdir(parents=True)
    _atomic_json(pending / "protocol" / "frozen_selection.json", selection)
    shutil.copy2(codebook, pending / "protocol" / "annotation-codebook.md")

    project = selection["project"]
    source_root = snapshots / project["id"]
    source_row = _validate_project_snapshot(project, source_root, selection["packet_limits"])
    packet_count = 0
    for slot in selection["annotator_slots"]:
        packet_root = pending / "annotation_packets" / slot["id"] / project["id"]
        _copy_project_snapshot(source_root, packet_root)
        packet_manifest = {
            "schema_version": CALIBRATION_PACKET_SCHEMA,
            "selection_sha256": selection_hash,
            "codebook_sha256": selection["codebook"]["sha256"],
            "project_id": project["id"],
            "annotator_slot_id": slot["id"],
            "snapshot_sha256": source_row["snapshot_sha256"],
            "file_count": source_row["file_count"],
            "byte_count": source_row["byte_count"],
            "evidence_role": "training_only",
            "condition_prompts_included": False,
            "agent_outputs_included": False,
            "other_annotator_labels_included": False,
            "reuse_in_development_or_confirmation_prohibited": True,
        }
        _atomic_json(packet_root / "packet_manifest.json", packet_manifest)
        _atomic_json(
            packet_root / "annotation.template.json",
            {
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
            },
        )
        packet_count += 1

    source_manifest = {
        "schema_version": "APC_ANNOTATION_CALIBRATION_SOURCE_MANIFEST_V1",
        "selection_sha256": selection_hash,
        "authority": "source_of_truth",
        "lifecycle_class": "validated",
        "public_distribution_includes_source": False,
        "projects": [source_row],
    }
    _atomic_json(pending / "controller" / "source_manifest.json", source_manifest)
    discussion = {
        "schema_version": CALIBRATION_DISCUSSION_SCHEMA,
        "selection_sha256": selection_hash,
        "codebook_initial_sha256": selection["codebook"]["sha256"],
        "status": "pending_independent_human_practice",
        "independent_annotation_sha256": {},
        "disagreement_items": [],
        "codebook_decisions": [],
        "codebook_revised": None,
        "codebook_final_sha256": None,
        "completed_at": None,
        "reuse_in_development_or_confirmation_prohibited": True,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    _atomic_json(pending / "review" / "calibration_discussion.template.json", discussion)
    manifest = {
        "schema_version": CALIBRATION_MANIFEST_SCHEMA,
        "selection_id": selection["selection_id"],
        "run_group_id": run_group_id,
        "selection_sha256": selection_hash,
        "codebook_sha256": selection["codebook"]["sha256"],
        "created_at": _now(),
        "evidence_role": "training_only",
        "calibration_state": "pending_human_practice",
        "project_count": 1,
        "annotation_packet_count": packet_count,
        "excluded_from_development": True,
        "excluded_from_confirmation": True,
        "agent_execution_authorized": False,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
        "claim_boundary": selection["claim_boundary"],
    }
    _atomic_json(pending / "controller" / "calibration_manifest.json", manifest)

    tracked = [
        pending / "controller" / "calibration_manifest.json",
        pending / "controller" / "source_manifest.json",
        pending / "protocol" / "annotation-codebook.md",
        pending / "review" / "calibration_discussion.template.json",
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
        "calibration_state": "pending_human_practice",
        "reused_existing": False,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }


def _calibration_context(
    run_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _load_json(run_dir / "controller" / "calibration_manifest.json")
    _require(manifest.get("schema_version") == CALIBRATION_MANIFEST_SCHEMA, "invalid calibration manifest")
    selection = _load_json(run_dir / "protocol" / "frozen_selection.json")
    summary = validate_calibration_selection(selection)
    _require(
        manifest.get("selection_sha256") == summary["selection_sha256"],
        "calibration frozen selection identity mismatch",
    )
    source = _load_json(run_dir / "controller" / "source_manifest.json")
    _require(
        source.get("selection_sha256") == manifest["selection_sha256"],
        "calibration source selection identity mismatch",
    )
    source_rows = source.get("projects")
    _require(
        isinstance(source_rows, list)
        and len(source_rows) == 1
        and source_rows[0].get("project_id") == selection["project"]["id"],
        "calibration source project coverage mismatch",
    )
    initial_codebook = run_dir / "protocol" / "annotation-codebook.md"
    _require(initial_codebook.is_file(), "calibration initial codebook is missing")
    _require(
        _file_sha256(initial_codebook) == selection["codebook"]["sha256"],
        "calibration initial codebook SHA-256 mismatch",
    )
    return manifest, selection, source


def _collect_calibration_annotations(
    run_dir: Path,
    manifest: dict[str, Any],
    selection: dict[str, Any],
    source: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    project_id = selection["project"]["id"]
    snapshot_sha256 = source["projects"][0]["snapshot_sha256"]
    slot_ids = [row["id"] for row in selection["annotator_slots"]]
    raw_root = run_dir / "review" / "raw_labels"
    expected = {f"{slot_id}/{project_id}.json" for slot_id in slot_ids}
    actual = {
        path.relative_to(raw_root).as_posix()
        for path in raw_root.rglob("*.json")
        if path.is_file()
    } if raw_root.is_dir() else set()
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    _require(not missing, f"missing calibration annotation: {missing[0] if missing else ''}")
    _require(not extra, f"unexpected calibration annotation: {extra[0] if extra else ''}")

    hashes: dict[str, str] = {}
    identities: dict[str, str] = {}
    for slot_id in slot_ids:
        relative = f"{slot_id}/{project_id}.json"
        path = raw_root / relative
        artifact = _load_json(path)
        label = f"calibration/{relative}"
        _require(artifact.get("schema_version") == ANNOTATION_SCHEMA, f"invalid annotation schema: {label}")
        _require(artifact.get("selection_sha256") == manifest["selection_sha256"], f"annotation selection mismatch: {label}")
        _require(artifact.get("project_id") == project_id, f"annotation project mismatch: {label}")
        _require(artifact.get("annotator_slot_id") == slot_id, f"annotation slot mismatch: {label}")
        _require(artifact.get("snapshot_sha256") == snapshot_sha256, f"annotation snapshot mismatch: {label}")
        annotator_id = _nonempty_text(artifact.get("annotator_id"), f"{label} annotator_id")
        identities[slot_id] = annotator_id
        _require(artifact.get("completed") is True, f"annotation is not complete: {label}")
        attestation = artifact.get("human_attestation")
        _require(isinstance(attestation, dict), f"missing human attestation: {label}")
        for field in ("human_annotator", "independent", "condition_blinded", "no_agent_outputs_reviewed"):
            _require(attestation.get(field) is True, f"annotation attestation {field} is not true: {label}")
        _nonempty_text(attestation.get("attested_at"), f"{label} attested_at")
        element_ids = _validate_element_inventory(artifact.get("element_inventory"), label)
        _validate_candidate_findings(artifact.get("candidate_findings"), element_ids, label)
        hashes[relative] = _file_sha256(path)
    _require(len(set(identities.values())) == len(slot_ids), "calibration annotator identities must be distinct")
    return dict(sorted(hashes.items())), dict(sorted(identities.items()))


def calibration_label_preflight(run_dir: Path | str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    manifest, selection, source = _calibration_context(run_dir)
    raw_hashes, identities = _collect_calibration_annotations(
        run_dir, manifest, selection, source
    )
    return {
        "schema_version": "APC_ANNOTATION_CALIBRATION_LABEL_PREFLIGHT_V1",
        "run_group_id": manifest["run_group_id"],
        "selection_sha256": manifest["selection_sha256"],
        "raw_annotation_count": len(raw_hashes),
        "independent_human_annotators": len(set(identities.values())),
        "raw_label_sha256": raw_hashes,
        "annotator_identity_sha256": {
            slot_id: hashlib.sha256(identity.encode("utf-8")).hexdigest()
            for slot_id, identity in identities.items()
        },
        "status": "independent_practice_labels_validated_pending_discussion",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }


def _validate_calibration_discussion(
    discussion: dict[str, Any],
    manifest: dict[str, Any],
    selection: dict[str, Any],
    raw_hashes: dict[str, str],
    final_codebook: Path,
) -> None:
    _require(
        discussion.get("schema_version") == CALIBRATION_DISCUSSION_SCHEMA,
        "invalid calibration discussion schema",
    )
    _require(
        discussion.get("selection_sha256") == manifest["selection_sha256"],
        "calibration discussion selection mismatch",
    )
    _require(
        discussion.get("codebook_initial_sha256") == selection["codebook"]["sha256"],
        "calibration discussion initial codebook mismatch",
    )
    _require(discussion.get("status") == "complete", "calibration discussion is not complete")
    _require(
        discussion.get("independent_annotation_sha256") == raw_hashes,
        "calibration discussion annotation hashes mismatch",
    )
    _require(
        isinstance(discussion.get("disagreement_items"), list),
        "calibration disagreement_items must be an array",
    )
    _require(
        isinstance(discussion.get("codebook_decisions"), list),
        "calibration codebook_decisions must be an array",
    )
    revised = discussion.get("codebook_revised")
    _require(isinstance(revised, bool), "calibration codebook_revised must be boolean")
    final_hash = _file_sha256(final_codebook)
    _require(
        discussion.get("codebook_final_sha256") == final_hash,
        "calibration final codebook SHA-256 mismatch",
    )
    if revised:
        _require(final_hash != selection["codebook"]["sha256"], "revised codebook hash did not change")
    else:
        _require(final_hash == selection["codebook"]["sha256"], "unchanged codebook hash changed")
    _nonempty_text(discussion.get("completed_at"), "calibration discussion completed_at")
    _require(
        discussion.get("reuse_in_development_or_confirmation_prohibited") is True,
        "calibration discussion violates study-reuse prohibition",
    )
    _require(discussion.get("paper_table_eligible") is False, "calibration discussion paper flag must be false")
    _require(
        discussion.get("general_reliability_proved") is False,
        "calibration discussion general-reliability flag must be false",
    )


def _calibration_set_material(
    manifest: dict[str, Any],
    selection: dict[str, Any],
    source: dict[str, Any],
    raw_hashes: dict[str, str],
    identities: dict[str, str],
    discussion_path: Path,
    final_codebook: Path,
) -> dict[str, Any]:
    return {
        "calibration_run_group_id": manifest["run_group_id"],
        "calibration_selection_sha256": manifest["selection_sha256"],
        "project_id": selection["project"]["id"],
        "snapshot_sha256": source["projects"][0]["snapshot_sha256"],
        "codebook_initial_sha256": selection["codebook"]["sha256"],
        "codebook_final_sha256": _file_sha256(final_codebook),
        "raw_label_sha256": raw_hashes,
        "annotator_identity_sha256": {
            slot_id: hashlib.sha256(identity.encode("utf-8")).hexdigest()
            for slot_id, identity in identities.items()
        },
        "discussion_sha256": _file_sha256(discussion_path),
    }


def _validate_calibration_commitment(run_dir: Path, commitment: dict[str, Any]) -> None:
    try:
        manifest, selection, source = _calibration_context(run_dir)
        _require(
            commitment.get("schema_version") == CALIBRATION_COMMITMENT_SCHEMA,
            "unsupported calibration commitment schema",
        )
        raw_hashes, identities = _collect_calibration_annotations(
            run_dir, manifest, selection, source
        )
        discussion_path = run_dir / "review" / "calibration_discussion.json"
        _require(discussion_path.is_file(), "calibration discussion is missing")
        discussion = _load_json(discussion_path)
        final_codebook = run_dir / "protocol" / "final-annotation-codebook.md"
        _require(final_codebook.is_file(), "final calibration codebook is missing")
        _validate_calibration_discussion(
            discussion, manifest, selection, raw_hashes, final_codebook
        )
        material = _calibration_set_material(
            manifest, selection, source, raw_hashes, identities, discussion_path, final_codebook
        )
        expected = {
            "commitment_state": "frozen",
            "calibration_completed": True,
            "evidence_role": "training_only",
            "raw_annotation_count": len(raw_hashes),
            "independent_human_annotators": len(identities),
            **material,
            "calibration_set_sha256": canonical_hash(material),
            "reuse_in_development_or_confirmation_prohibited": True,
            "paper_table_eligible": False,
            "general_reliability_proved": False,
        }
        for field, value in expected.items():
            _require(commitment.get(field) == value, f"field {field}")
        _nonempty_text(commitment.get("frozen_at"), "calibration commitment frozen_at")
    except ContractError as exc:
        raise ContractError(f"calibration commitment mismatch: {exc}") from exc


def freeze_calibration(
    run_dir: Path | str,
    final_codebook_path: Path | str,
) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    supplied_codebook = Path(final_codebook_path).resolve()
    _require(supplied_codebook.is_file(), f"final codebook is missing: {supplied_codebook}")
    commitment_path = run_dir / "review" / "calibration_commitment.json"
    if commitment_path.is_file():
        commitment = _load_json(commitment_path)
        _validate_calibration_commitment(run_dir, commitment)
        _require(
            _file_sha256(supplied_codebook) == commitment["codebook_final_sha256"],
            "supplied final codebook differs from frozen calibration commitment",
        )
        return {**commitment, "commitment_path": str(commitment_path), "reused_existing": True}

    manifest, selection, source = _calibration_context(run_dir)
    raw_hashes, identities = _collect_calibration_annotations(
        run_dir, manifest, selection, source
    )
    discussion_path = run_dir / "review" / "calibration_discussion.json"
    _require(discussion_path.is_file(), "calibration discussion is missing")
    discussion = _load_json(discussion_path)
    _validate_calibration_discussion(
        discussion, manifest, selection, raw_hashes, supplied_codebook
    )
    frozen_codebook = run_dir / "protocol" / "final-annotation-codebook.md"
    if frozen_codebook.is_file():
        _require(
            _file_sha256(frozen_codebook) == _file_sha256(supplied_codebook),
            "existing final calibration codebook identity mismatch",
        )
    else:
        pending = frozen_codebook.with_name(f".{frozen_codebook.name}.pending")
        _require(not pending.exists(), f"pending final codebook requires review: {pending}")
        shutil.copy2(supplied_codebook, pending)
        pending.replace(frozen_codebook)
    material = _calibration_set_material(
        manifest, selection, source, raw_hashes, identities, discussion_path, frozen_codebook
    )
    commitment = {
        "schema_version": CALIBRATION_COMMITMENT_SCHEMA,
        "commitment_state": "frozen",
        "calibration_completed": True,
        "evidence_role": "training_only",
        "raw_annotation_count": len(raw_hashes),
        "independent_human_annotators": len(identities),
        **material,
        "calibration_set_sha256": canonical_hash(material),
        "frozen_at": _now(),
        "reuse_in_development_or_confirmation_prohibited": True,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    _atomic_json(commitment_path, commitment)
    _validate_calibration_commitment(run_dir, _load_json(commitment_path))
    return {**commitment, "commitment_path": str(commitment_path), "reused_existing": False}

def calibration_status(run_dir: Path | str) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    manifest, _, _ = _calibration_context(run_dir)
    commitment_path = run_dir / "review" / "calibration_commitment.json"
    discussion_path = run_dir / "review" / "calibration_discussion.json"
    if commitment_path.is_file():
        commitment = _load_json(commitment_path)
        _validate_calibration_commitment(run_dir, commitment)
        state = "complete"
    elif discussion_path.is_file():
        calibration_label_preflight(run_dir)
        state = "pending_calibration_freeze"
    else:
        state = "pending_human_practice"
    return {
        "run_group_id": manifest["run_group_id"],
        "selection_sha256": manifest["selection_sha256"],
        "calibration_state": state,
        "human_action_required": state == "pending_human_practice",
        "calibration_freeze_required": state == "pending_calibration_freeze",
        "agent_execution_authorized": False,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--selection", required=True, type=Path)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--selection", required=True, type=Path)
    prepare.add_argument("--snapshot-root", required=True, type=Path)
    prepare.add_argument("--output-root", required=True, type=Path)
    prepare.add_argument("--codebook", required=True, type=Path)
    labels = commands.add_parser("label-preflight")
    labels.add_argument("--run-dir", required=True, type=Path)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--run-dir", required=True, type=Path)
    freeze.add_argument("--final-codebook", required=True, type=Path)
    status = commands.add_parser("status")
    status.add_argument("--run-dir", required=True, type=Path)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        if args.command == "preflight":
            result = validate_calibration_selection(_load_json(args.selection.resolve()))
            result["status"] = "calibration_selection_preflight_passed"
        elif args.command == "prepare":
            result = prepare_calibration_workspace(
                args.selection,
                args.snapshot_root,
                args.output_root,
                args.codebook,
            )
        elif args.command == "label-preflight":
            result = calibration_label_preflight(args.run_dir)
        elif args.command == "freeze":
            result = freeze_calibration(args.run_dir, args.final_codebook)
        else:
            result = calibration_status(args.run_dir)
    except ContractError as exc:
        raise SystemExit(f"contract error: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

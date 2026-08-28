"""Closed evaluation-attempt manifest for bounded skill-quality comparisons."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .contract import QualityError, canonical_bytes


SCHEMA_VERSION = 1
MAX_MANIFEST_BYTES = 16384
MAX_RESULT_BYTES = 131072
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
TOP_KEYS = {
    "schema_version",
    "kind",
    "evaluation_id",
    "problem_signature_sha256",
    "baseline_package",
    "candidate_package",
    "fixtures",
    "environment",
    "model",
    "rules",
    "created_at_utc",
    "manifest_digest_sha256",
}
PACKAGE_KEYS = {"owner", "repository", "skill", "version", "package_digest_sha256"}
FIXTURE_KEYS = {
    "fixture_id",
    "fixture_digest_sha256",
    "taxonomy_id",
    "capability_id",
    "environment_class",
    "invariant_id",
    "producer_repository",
    "quality_signal",
}
ENVIRONMENT_KEYS = {
    "platform_id",
    "runner_image_digest_sha256",
    "dependency_lock_digest_sha256",
}
MODEL_KEYS = {"provider", "model", "parameters_digest_sha256", "pinned"}
RULE_KEYS = {
    "ruleset_id",
    "ruleset_digest_sha256",
    "repetitions",
    "minimum_receipt_count",
    "maximum_receipt_count",
    "minimum_baseline_reproducibility_basis_points",
    "maximum_false_cluster_basis_points",
    "minimum_improvement_basis_points",
    "maximum_regression_basis_points",
}
RESULT_TOP_KEYS = {
    "schema_version",
    "kind",
    "evaluation_id",
    "manifest_digest_sha256",
    "fixture_results",
    "summary",
    "classification",
    "executed_at_utc",
    "result_digest_sha256",
}
RESULT_FIXTURE_KEYS = {
    "fixture_id",
    "fixture_digest_sha256",
    "baseline_replay_matches",
    "baseline_replay_total",
    "problem_cluster_correct",
    "owner_disposition",
    "owner_authoring_seconds",
    "baseline_score_basis_points",
    "candidate_score_basis_points",
    "maximum_regression_basis_points",
    "unauthorized_outbound_actions",
}
SUMMARY_KEYS = {
    "receipt_count",
    "baseline_replay_reproducibility_basis_points",
    "false_problem_cluster_basis_points",
    "primary_improvement_basis_points",
    "maximum_observed_regression_basis_points",
    "total_owner_authoring_seconds",
    "unauthorized_outbound_actions",
}
CLASSIFICATION_KEYS = {"status", "reason_codes"}
OWNER_DISPOSITIONS = {"accepted", "deferred", "rejected"}
CLASSIFICATION_STATUSES = {"PASS", "FAIL", "INCONCLUSIVE"}
PILOT_QUALITY_SIGNALS = {
    "claim_evidence_gap",
    "documentation_mismatch",
    "internal_failure",
    "lifecycle_inconsistency",
}


def _error(message: str) -> QualityError:
    return QualityError("EVALUATION_SCHEMA_VIOLATION", message)


def _result_error(message: str) -> QualityError:
    return QualityError("EVALUATION_RESULT_SCHEMA_VIOLATION", message)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise _error("created_at requires a timezone.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise _error(f"{field} is invalid.")
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise _error(f"{field} must be a lowercase SHA-256 digest.")
    return value


def _closed(value: object, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _error(f"{field} has unknown or missing fields.")
    return value


def _result_closed(value: object, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _result_error(f"{field} has unknown or missing fields.")
    return value


def _integer(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
    result: bool = False,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        factory = _result_error if result else _error
        raise factory(f"{field} must be an integer from {minimum} through {maximum}.")
    return value


def _package(value: object, field: str) -> dict[str, Any]:
    item = _closed(value, PACKAGE_KEYS, field)
    if item.get("owner") != "Ian-Tseng":
        raise _error(f"{field}.owner must be Ian-Tseng.")
    for key in ("repository", "skill"):
        _identifier(item.get(key), f"{field}.{key}")
    if not isinstance(item.get("version"), str) or not SEMVER.fullmatch(item["version"]):
        raise _error(f"{field}.version is invalid.")
    _sha(item.get("package_digest_sha256"), f"{field}.package_digest_sha256")
    return item


def _canonical_created_at(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _error("created_at_utc must be RFC 3339 UTC.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise _error("created_at_utc is invalid.") from exc
    if parsed.microsecond or _utc_text(parsed) != value:
        raise _error("created_at_utc must use canonical whole UTC seconds.")
    return value


def manifest_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("manifest_digest_sha256", None)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def validate_evaluation_manifest(value: object) -> dict[str, Any]:
    item = _closed(value, TOP_KEYS, "manifest")
    if len(canonical_bytes(item)) > MAX_MANIFEST_BYTES:
        raise QualityError("EVALUATION_TOO_LARGE", "Evaluation manifest exceeds its byte limit.")
    if item.get("schema_version") != SCHEMA_VERSION or item.get("kind") != "skill-quality-evaluation":
        raise _error("Evaluation manifest version or kind is unsupported.")
    _identifier(item.get("evaluation_id"), "evaluation_id")
    _sha(item.get("problem_signature_sha256"), "problem_signature_sha256")
    _package(item.get("baseline_package"), "baseline_package")
    _package(item.get("candidate_package"), "candidate_package")
    if item["baseline_package"] == item["candidate_package"]:
        raise _error("Baseline and candidate package identities must differ.")

    fixtures = item.get("fixtures")
    if not isinstance(fixtures, list) or not 1 <= len(fixtures) <= 256:
        raise _error("fixtures must contain between 1 and 256 entries.")
    fixture_ids: set[str] = set()
    fixture_digests: set[str] = set()
    for index, value_fixture in enumerate(fixtures):
        fixture = _closed(value_fixture, FIXTURE_KEYS, f"fixtures[{index}]")
        fixture_id = _identifier(fixture.get("fixture_id"), f"fixtures[{index}].fixture_id")
        if fixture_id in fixture_ids:
            raise _error("fixture_id values must be unique.")
        fixture_ids.add(fixture_id)
        fixture_digest = _sha(
            fixture.get("fixture_digest_sha256"),
            f"fixtures[{index}].fixture_digest_sha256",
        )
        if fixture_digest in fixture_digests:
            raise _error("fixture_digest_sha256 values must identify distinct receipts.")
        fixture_digests.add(fixture_digest)
        _identifier(fixture.get("taxonomy_id"), f"fixtures[{index}].taxonomy_id")
        _identifier(fixture.get("capability_id"), f"fixtures[{index}].capability_id")
        _identifier(fixture.get("environment_class"), f"fixtures[{index}].environment_class")
        _identifier(fixture.get("invariant_id"), f"fixtures[{index}].invariant_id")
        _identifier(fixture.get("producer_repository"), f"fixtures[{index}].producer_repository")
        quality_signal = _identifier(
            fixture.get("quality_signal"),
            f"fixtures[{index}].quality_signal",
        )
        if quality_signal not in PILOT_QUALITY_SIGNALS:
            raise _error(f"fixtures[{index}].quality_signal is outside the frozen pilot taxonomy.")

    environment = _closed(item.get("environment"), ENVIRONMENT_KEYS, "environment")
    _identifier(environment.get("platform_id"), "environment.platform_id")
    _sha(environment.get("runner_image_digest_sha256"), "environment.runner_image_digest_sha256")
    _sha(environment.get("dependency_lock_digest_sha256"), "environment.dependency_lock_digest_sha256")

    model = _closed(item.get("model"), MODEL_KEYS, "model")
    _identifier(model.get("provider"), "model.provider")
    _identifier(model.get("model"), "model.model")
    _sha(model.get("parameters_digest_sha256"), "model.parameters_digest_sha256")
    if not isinstance(model.get("pinned"), bool):
        raise _error("model.pinned must be boolean.")

    rules = _closed(item.get("rules"), RULE_KEYS, "rules")
    _identifier(rules.get("ruleset_id"), "rules.ruleset_id")
    _sha(rules.get("ruleset_digest_sha256"), "rules.ruleset_digest_sha256")
    repetitions = rules.get("repetitions")
    _integer(repetitions, "rules.repetitions", minimum=1, maximum=100)
    minimum_receipts = _integer(
        rules.get("minimum_receipt_count"),
        "rules.minimum_receipt_count",
        minimum=1,
        maximum=256,
    )
    maximum_receipts = _integer(
        rules.get("maximum_receipt_count"),
        "rules.maximum_receipt_count",
        minimum=1,
        maximum=256,
    )
    if minimum_receipts > maximum_receipts:
        raise _error("rules.minimum_receipt_count must not exceed maximum_receipt_count.")
    for field in (
        "minimum_baseline_reproducibility_basis_points",
        "maximum_false_cluster_basis_points",
        "minimum_improvement_basis_points",
        "maximum_regression_basis_points",
    ):
        _integer(rules.get(field), f"rules.{field}", minimum=0, maximum=10000)

    _canonical_created_at(item.get("created_at_utc"))
    expected = manifest_digest(item)
    if item.get("manifest_digest_sha256") != expected:
        raise QualityError(
            "EVALUATION_DIGEST_MISMATCH",
            "Evaluation manifest digest does not match its canonical payload.",
        )
    return json.loads(canonical_bytes(item).decode("utf-8"))


def create_evaluation_manifest(
    *,
    evaluation_id: str,
    problem_signature_sha256: str,
    baseline_package: Mapping[str, Any],
    candidate_package: Mapping[str, Any],
    fixtures: Sequence[Mapping[str, Any]],
    environment: Mapping[str, Any],
    model: Mapping[str, Any],
    rules: Mapping[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "skill-quality-evaluation",
        "evaluation_id": evaluation_id,
        "problem_signature_sha256": problem_signature_sha256,
        "baseline_package": dict(baseline_package),
        "candidate_package": dict(candidate_package),
        "fixtures": [dict(fixture) for fixture in fixtures],
        "environment": dict(environment),
        "model": dict(model),
        "rules": dict(rules),
        "created_at_utc": _utc_text(created_at),
    }
    manifest["manifest_digest_sha256"] = manifest_digest(manifest)
    return validate_evaluation_manifest(manifest)


def evaluation_readiness(value: object) -> str:
    manifest = validate_evaluation_manifest(value)
    return "READY" if manifest["model"]["pinned"] else "INCONCLUSIVE"


def result_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("result_digest_sha256", None)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _validate_result_fixture(value: object, index: int) -> dict[str, Any]:
    field = f"fixture_results[{index}]"
    item = _result_closed(value, RESULT_FIXTURE_KEYS, field)
    _identifier(item.get("fixture_id"), f"{field}.fixture_id")
    _sha(item.get("fixture_digest_sha256"), f"{field}.fixture_digest_sha256")
    total = _integer(
        item.get("baseline_replay_total"),
        f"{field}.baseline_replay_total",
        minimum=1,
        maximum=100,
        result=True,
    )
    matches = _integer(
        item.get("baseline_replay_matches"),
        f"{field}.baseline_replay_matches",
        minimum=0,
        maximum=100,
        result=True,
    )
    if matches > total:
        raise _result_error(f"{field}.baseline_replay_matches exceeds its denominator.")
    if not isinstance(item.get("problem_cluster_correct"), bool):
        raise _result_error(f"{field}.problem_cluster_correct must be boolean.")
    if item.get("owner_disposition") not in OWNER_DISPOSITIONS:
        raise _result_error(f"{field}.owner_disposition is invalid.")
    _integer(
        item.get("owner_authoring_seconds"),
        f"{field}.owner_authoring_seconds",
        minimum=0,
        maximum=604800,
        result=True,
    )
    for metric in (
        "baseline_score_basis_points",
        "candidate_score_basis_points",
        "maximum_regression_basis_points",
    ):
        _integer(item.get(metric), f"{field}.{metric}", minimum=0, maximum=10000, result=True)
    _integer(
        item.get("unauthorized_outbound_actions"),
        f"{field}.unauthorized_outbound_actions",
        minimum=0,
        maximum=10000,
        result=True,
    )
    return item


def _result_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    if not rows:
        raise _result_error("fixture_results must contain between 1 and 256 entries.")
    replay_total = sum(row["baseline_replay_total"] for row in rows)
    replay_matches = sum(row["baseline_replay_matches"] for row in rows)
    receipt_count = len({row["fixture_digest_sha256"] for row in rows})
    false_clusters = sum(not row["problem_cluster_correct"] for row in rows)
    return {
        "receipt_count": receipt_count,
        "baseline_replay_reproducibility_basis_points": replay_matches * 10000 // replay_total,
        "false_problem_cluster_basis_points": false_clusters * 10000 // receipt_count,
        "primary_improvement_basis_points": sum(
            row["candidate_score_basis_points"] - row["baseline_score_basis_points"]
            for row in rows
        )
        // receipt_count,
        "maximum_observed_regression_basis_points": max(
            row["maximum_regression_basis_points"] for row in rows
        ),
        "total_owner_authoring_seconds": sum(row["owner_authoring_seconds"] for row in rows),
        "unauthorized_outbound_actions": sum(
            row["unauthorized_outbound_actions"] for row in rows
        ),
    }


def _result_classification(
    manifest: Mapping[str, Any],
    summary: Mapping[str, int],
) -> dict[str, Any]:
    rules = manifest["rules"]
    reasons: list[str] = []
    inconclusive = False
    failed = False
    if not manifest["model"]["pinned"]:
        reasons.append("MODEL_UNPINNED")
        inconclusive = True
    if not rules["minimum_receipt_count"] <= summary["receipt_count"] <= rules["maximum_receipt_count"]:
        reasons.append("RECEIPT_COUNT_OUT_OF_RANGE")
        inconclusive = True
    if (
        summary["baseline_replay_reproducibility_basis_points"]
        < rules["minimum_baseline_reproducibility_basis_points"]
    ):
        reasons.append("BASELINE_REPRODUCIBILITY_BELOW_THRESHOLD")
        failed = True
    if summary["false_problem_cluster_basis_points"] > rules["maximum_false_cluster_basis_points"]:
        reasons.append("FALSE_CLUSTER_RATE_ABOVE_THRESHOLD")
        failed = True
    if summary["primary_improvement_basis_points"] < rules["minimum_improvement_basis_points"]:
        reasons.append("PRIMARY_IMPROVEMENT_BELOW_THRESHOLD")
        failed = True
    if summary["maximum_observed_regression_basis_points"] > rules["maximum_regression_basis_points"]:
        reasons.append("REGRESSION_ABOVE_THRESHOLD")
        failed = True
    if summary["unauthorized_outbound_actions"]:
        reasons.append("UNAUTHORIZED_OUTBOUND_ACTION")
        failed = True
    status = "FAIL" if failed else "INCONCLUSIVE" if inconclusive else "PASS"
    return {"status": status, "reason_codes": sorted(reasons)}


def validate_evaluation_result(
    manifest_value: object,
    result_value: object,
) -> dict[str, Any]:
    manifest = validate_evaluation_manifest(manifest_value)
    item = _result_closed(result_value, RESULT_TOP_KEYS, "result")
    if len(canonical_bytes(item)) > MAX_RESULT_BYTES:
        raise QualityError("EVALUATION_RESULT_TOO_LARGE", "Evaluation result exceeds its byte limit.")
    if item.get("schema_version") != SCHEMA_VERSION or item.get("kind") != "skill-quality-evaluation-result":
        raise _result_error("Evaluation result version or kind is unsupported.")
    _identifier(item.get("evaluation_id"), "evaluation_id")
    _sha(item.get("manifest_digest_sha256"), "manifest_digest_sha256")
    if (
        item["evaluation_id"] != manifest["evaluation_id"]
        or item["manifest_digest_sha256"] != manifest["manifest_digest_sha256"]
    ):
        raise QualityError(
            "EVALUATION_RESULT_MANIFEST_MISMATCH",
            "Evaluation result does not bind the supplied manifest identity.",
        )

    raw_rows = item.get("fixture_results")
    if not isinstance(raw_rows, list) or not 1 <= len(raw_rows) <= 256:
        raise _result_error("fixture_results must contain between 1 and 256 entries.")
    rows = [_validate_result_fixture(row, index) for index, row in enumerate(raw_rows)]
    row_identities = [(row["fixture_id"], row["fixture_digest_sha256"]) for row in rows]
    manifest_identities = [
        (fixture["fixture_id"], fixture["fixture_digest_sha256"])
        for fixture in manifest["fixtures"]
    ]
    if len(set(row_identities)) != len(row_identities) or set(row_identities) != set(manifest_identities):
        raise QualityError(
            "EVALUATION_RESULT_FIXTURE_MISMATCH",
            "Evaluation result must cover every frozen manifest fixture exactly once.",
        )
    if any(row["baseline_replay_total"] != manifest["rules"]["repetitions"] for row in rows):
        raise QualityError(
            "EVALUATION_RESULT_REPETITION_MISMATCH",
            "Every result row must cover the manifest repetition count.",
        )

    summary = _result_closed(item.get("summary"), SUMMARY_KEYS, "summary")
    expected_summary = _result_summary(rows)
    if summary != expected_summary:
        raise QualityError(
            "EVALUATION_RESULT_SUMMARY_MISMATCH",
            "Evaluation result summary does not match its fixture rows.",
        )
    classification = _result_closed(
        item.get("classification"),
        CLASSIFICATION_KEYS,
        "classification",
    )
    if classification.get("status") not in CLASSIFICATION_STATUSES:
        raise _result_error("classification.status is invalid.")
    reason_codes = classification.get("reason_codes")
    if (
        not isinstance(reason_codes, list)
        or any(not isinstance(reason, str) or not IDENTIFIER.fullmatch(reason) for reason in reason_codes)
        or reason_codes != sorted(set(reason_codes))
    ):
        raise _result_error("classification.reason_codes must be unique sorted identifiers.")
    if classification != _result_classification(manifest, summary):
        raise QualityError(
            "EVALUATION_RESULT_CLASSIFICATION_MISMATCH",
            "Evaluation result classification does not match the frozen gates.",
        )
    executed_at = _canonical_created_at(item.get("executed_at_utc"))
    if executed_at < manifest["created_at_utc"]:
        raise QualityError(
            "EVALUATION_RESULT_TIME_MISMATCH",
            "Evaluation result cannot predate its manifest.",
        )
    expected_digest = result_digest(item)
    if item.get("result_digest_sha256") != expected_digest:
        raise QualityError(
            "EVALUATION_RESULT_DIGEST_MISMATCH",
            "Evaluation result digest does not match its canonical payload.",
        )
    return json.loads(canonical_bytes(item).decode("utf-8"))


def create_evaluation_result(
    *,
    manifest: Mapping[str, Any],
    fixture_results: Sequence[Mapping[str, Any]],
    executed_at: datetime,
) -> dict[str, Any]:
    valid_manifest = validate_evaluation_manifest(manifest)
    rows = [
        _validate_result_fixture(dict(row), index)
        for index, row in enumerate(fixture_results)
    ]
    summary = _result_summary(rows)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "skill-quality-evaluation-result",
        "evaluation_id": valid_manifest["evaluation_id"],
        "manifest_digest_sha256": valid_manifest["manifest_digest_sha256"],
        "fixture_results": rows,
        "summary": summary,
        "classification": _result_classification(valid_manifest, summary),
        "executed_at_utc": _utc_text(executed_at),
    }
    result["result_digest_sha256"] = result_digest(result)
    return validate_evaluation_result(valid_manifest, result)

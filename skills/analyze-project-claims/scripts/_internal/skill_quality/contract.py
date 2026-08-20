"""Closed, content-free SkillOutcomeReceipt v1 contract."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


SCHEMA_VERSION = 1
MAX_RECEIPT_BYTES = 3072
MAX_MARKER_BYTES = 4096
MAX_ASSISTANT_MESSAGE_BYTES = 65536
MAX_FUTURE_SKEW_SECONDS = 300
MARKER_PREFIX = "SKILL_OUTCOME_RECEIPT_V1:"
IDENTIFIER = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
OUTCOMES = {"completed", "completed_with_limitations", "failed"}
QUALITY_SIGNALS = {
    "claim_evidence_gap",
    "lifecycle_inconsistency",
    "documentation_mismatch",
    "internal_failure",
    "no_issue",
}
REQUESTED_ACTIONS = {"analyze_quality", "none"}
RECEIPT_KEYS = {
    "schema_version",
    "receipt_id",
    "producer",
    "outcome",
    "quality_signal",
    "requested_action",
    "action_performed",
    "created_at_utc",
    "expires_at_utc",
    "causal_depth",
    "prior_receipt_digest_sha256",
    "receipt_digest_sha256",
}
PRODUCER_KEYS = {
    "owner",
    "repository",
    "skill",
    "version",
    "package_digest_sha256",
    "identity_authority",
}


class QualityError(RuntimeError):
    """A stable, user-actionable quality-loop failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt timestamps require a timezone.")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", f"{field} must be RFC 3339 UTC.")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", f"{field} is invalid.") from exc
    if parsed.microsecond:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", f"{field} must use whole seconds.")
    if _utc_text(parsed) != value:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", f"{field} must use canonical RFC 3339 UTC seconds.")
    return parsed


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "receipt_id must be a UUIDv4 string.")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "receipt_id must be a UUIDv4 string.") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "receipt_id must be canonical UUIDv4.")
    return value


def _validate_producer(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != PRODUCER_KEYS:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "producer has unknown or missing fields.")
    if value.get("owner") != "Ian-Tseng":
        raise QualityError("RECEIPT_PRODUCER_UNSUPPORTED", "Only declared Ian-Tseng producers are supported in v1.")
    if not isinstance(value.get("repository"), str) or not REPOSITORY.fullmatch(value["repository"]):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "producer.repository is invalid.")
    if not isinstance(value.get("skill"), str) or not IDENTIFIER.fullmatch(value["skill"]):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "producer.skill is invalid.")
    if not isinstance(value.get("version"), str) or not SEMVER.fullmatch(value["version"]):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "producer.version is invalid.")
    if not isinstance(value.get("package_digest_sha256"), str) or not SHA256.fullmatch(
        value["package_digest_sha256"]
    ):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "producer package digest is invalid.")
    if value.get("identity_authority") != "producer_declared_untrusted":
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "producer identity authority is invalid.")
    return dict(value)


def receipt_digest(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("receipt_digest_sha256", None)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def validate_receipt(
    value: object,
    *,
    now: datetime | None = None,
    require_unexpired: bool = True,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != RECEIPT_KEYS:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt has unknown or missing fields.")
    if len(canonical_bytes(value)) > MAX_RECEIPT_BYTES:
        raise QualityError("RECEIPT_TOO_LARGE", "Receipt exceeds the v1 size limit.")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt schema version is unsupported.")
    _canonical_uuid(value.get("receipt_id"))
    _validate_producer(value.get("producer"))
    if value.get("outcome") not in OUTCOMES:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt outcome is invalid.")
    if value.get("quality_signal") not in QUALITY_SIGNALS:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt quality signal is invalid.")
    if value.get("requested_action") not in REQUESTED_ACTIONS:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt requested action is invalid.")
    expected_action = "none" if value.get("quality_signal") == "no_issue" else "analyze_quality"
    if value.get("requested_action") != expected_action:
        raise QualityError(
            "RECEIPT_SCHEMA_VIOLATION",
            f"{value.get('quality_signal')} requires requested_action {expected_action}.",
        )
    if value.get("action_performed") is not False:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt cannot claim an action was performed.")
    depth = value.get("causal_depth")
    if not isinstance(depth, int) or isinstance(depth, bool) or depth not in {0, 1}:
        raise QualityError("RECEIPT_RECURSION_LIMIT", "Receipt causal depth must be zero or one.")
    prior = value.get("prior_receipt_digest_sha256")
    if prior is not None and (not isinstance(prior, str) or not SHA256.fullmatch(prior)):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Prior receipt digest is invalid.")
    if depth == 0 and prior is not None:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "A depth-zero receipt cannot name a prior receipt.")
    if depth == 1 and prior is None:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "A depth-one receipt requires a prior digest.")
    created = _parse_utc(value.get("created_at_utc"), "created_at_utc")
    expires = _parse_utc(value.get("expires_at_utc"), "expires_at_utc")
    if expires <= created or expires - created > timedelta(days=1):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt lifetime must be positive and at most 24 hours.")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if created > current + timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
        raise QualityError("RECEIPT_FUTURE_DATED", "Receipt creation time exceeds the allowed clock skew.")
    if require_unexpired and expires <= current:
        raise QualityError("RECEIPT_EXPIRED", "Receipt has expired.")
    expected = receipt_digest(value)
    if value.get("receipt_digest_sha256") != expected:
        raise QualityError("RECEIPT_DIGEST_MISMATCH", "Receipt digest does not match its canonical payload.")
    return json.loads(canonical_bytes(value).decode("utf-8"))


def create_receipt(
    *,
    owner: str,
    repository: str,
    skill: str,
    version: str,
    package_digest_sha256: str,
    outcome: str,
    quality_signal: str,
    requested_action: str,
    created_at: datetime,
    expires_at: datetime,
    causal_depth: int = 0,
    prior_receipt_digest_sha256: str | None = None,
    receipt_id: str | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id or str(uuid.uuid4()),
        "producer": {
            "owner": owner,
            "repository": repository,
            "skill": skill,
            "version": version,
            "package_digest_sha256": package_digest_sha256,
            "identity_authority": "producer_declared_untrusted",
        },
        "outcome": outcome,
        "quality_signal": quality_signal,
        "requested_action": requested_action,
        "action_performed": False,
        "created_at_utc": _utc_text(created_at),
        "expires_at_utc": _utc_text(expires_at),
        "causal_depth": causal_depth,
        "prior_receipt_digest_sha256": prior_receipt_digest_sha256,
    }
    receipt["receipt_digest_sha256"] = receipt_digest(receipt)
    return validate_receipt(receipt, now=created_at)


def format_marker(receipt: Mapping[str, Any]) -> str:
    validated = validate_receipt(dict(receipt))
    token = base64.urlsafe_b64encode(canonical_bytes(validated)).decode("ascii").rstrip("=")
    marker = MARKER_PREFIX + token
    if len(marker.encode("utf-8")) > MAX_MARKER_BYTES:
        raise QualityError("RECEIPT_TOO_LARGE", "Receipt marker exceeds the v1 size limit.")
    return marker


def parse_marker(marker: str, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(marker, str) or not marker.startswith(MARKER_PREFIX):
        raise QualityError("NO_COMPATIBLE_RECEIPT", "No v1 receipt marker was provided.")
    if len(marker.encode("utf-8")) > MAX_MARKER_BYTES or "\n" in marker or "\r" in marker:
        raise QualityError("RECEIPT_TOO_LARGE", "Receipt marker is oversized or multiline.")
    token = marker[len(MARKER_PREFIX) :]
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt marker encoding is invalid.")
    try:
        payload = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        value = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt marker is not canonical JSON.") from exc
    if canonical_bytes(value) != payload:
        raise QualityError("RECEIPT_SCHEMA_VIOLATION", "Receipt marker JSON is not canonical.")
    return validate_receipt(value, now=now)


def extract_trailing_marker(message: str, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(message, str):
        raise QualityError("NO_COMPATIBLE_RECEIPT", "The prior result has no assistant text.")
    if len(message.encode("utf-8")) > MAX_ASSISTANT_MESSAGE_BYTES:
        raise QualityError("RECEIPT_TOO_LARGE", "The assistant result exceeds the hook inspection limit.")
    final_line = message.rstrip("\r\n").rsplit("\n", 1)[-1]
    return parse_marker(final_line, now=now)

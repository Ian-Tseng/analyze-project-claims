"""Per-submission, enum-only owner contribution transport."""

from __future__ import annotations

import hashlib
import contextlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..safe_process import ExecutableResolutionError, resolve_executable
from . import contract
from .store import RECOMMENDATIONS


SCHEMA_VERSION = 1
DESTINATION_OWNER = "Ian-Tseng"
MAX_DRAFT_BYTES = 8192
MAX_APPROVAL_AGE_SECONDS = 86400
SUBPROCESS_TIMEOUT_SECONDS = 20
PROPOSAL_ID = re.compile(r"^quality-proposal-[0-9a-f]{24}$")
DRAFT_KEYS = {
    "schema_version",
    "contribution_id",
    "proposal_id",
    "receipt_digest_sha256",
    "analyzer_version",
    "producer_skill",
    "producer_repository",
    "producer_version",
    "producer_package_digest_sha256",
    "quality_signal",
    "recommended_action",
    "destination",
    "created_at_utc",
    "content_fingerprint_sha256",
    "approval_id",
}
SUBMISSION_KEYS = {
    "schema_version",
    "state",
    "contribution_id",
    "approval_id",
    "visibility",
    "issue_url",
    "updated_at_utc",
}
FINAL_NOTICE = (
    "This contribution contains only enum and package-identity fields. It does not include files, "
    "patches, paths, prompts, logs, project findings, or attachments."
)
AUTOMATION_NOTICE = (
    "Only Ian-Tseng may label this issue agent-ready. That label authorizes one isolated draft attempt, "
    "not merge, release, closure, component-map acceptance, or installed update."
)


class ContributionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fingerprint_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "schema_version",
            "contribution_id",
            "proposal_id",
            "receipt_digest_sha256",
            "analyzer_version",
            "producer_skill",
            "producer_repository",
            "producer_version",
            "producer_package_digest_sha256",
            "quality_signal",
            "recommended_action",
            "destination",
            "created_at_utc",
        )
    }


def content_fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(_fingerprint_fields(value))).hexdigest()


def approval_id(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("approval_id", None)
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _destination_for_repository(repository: object) -> str:
    if not isinstance(repository, str) or not contract.REPOSITORY.fullmatch(repository):
        raise ContributionError("CONTRIBUTION_DESTINATION_INVALID", "Producer repository is invalid.")
    return f"{DESTINATION_OWNER}/{repository}"


def _issue_url_pattern(destination: str) -> re.Pattern[str]:
    return re.compile(rf"https://github\.com/{re.escape(destination)}/issues/[1-9][0-9]*")


def validate_draft(value: object, *, now: datetime | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != DRAFT_KEYS:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Contribution has unknown or missing fields.")
    if len(_canonical(value)) > MAX_DRAFT_BYTES or value.get("schema_version") != SCHEMA_VERSION:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Contribution version or size is invalid.")
    try:
        contribution_id = str(uuid.UUID(value["contribution_id"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Contribution ID is invalid.") from exc
    if contribution_id != value["contribution_id"] or uuid.UUID(contribution_id).version != 4:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Contribution ID must be canonical UUIDv4.")
    if not isinstance(value["proposal_id"], str) or not PROPOSAL_ID.fullmatch(value["proposal_id"]):
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Proposal ID is invalid.")
    if not isinstance(value["receipt_digest_sha256"], str) or not contract.SHA256.fullmatch(
        value["receipt_digest_sha256"]
    ):
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Receipt digest is invalid.")
    if not isinstance(value["analyzer_version"], str) or not contract.SEMVER.fullmatch(value["analyzer_version"]):
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Analyzer version is invalid.")
    if not isinstance(value["producer_skill"], str) or not contract.IDENTIFIER.fullmatch(value["producer_skill"]):
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Producer skill is invalid.")
    if not isinstance(value["producer_repository"], str) or not contract.REPOSITORY.fullmatch(
        value["producer_repository"]
    ):
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Producer repository is invalid.")
    if not isinstance(value["producer_version"], str) or not contract.SEMVER.fullmatch(value["producer_version"]):
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Producer version is invalid.")
    if not isinstance(value["producer_package_digest_sha256"], str) or not contract.SHA256.fullmatch(
        value["producer_package_digest_sha256"]
    ):
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Producer package digest is invalid.")
    if value["quality_signal"] not in contract.QUALITY_SIGNALS:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Quality signal is invalid.")
    if value["recommended_action"] != RECOMMENDATIONS[value["quality_signal"]]:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Quality recommendation is inconsistent.")
    if value["destination"] != _destination_for_repository(value["producer_repository"]):
        raise ContributionError("CONTRIBUTION_DESTINATION_INVALID", "Contribution destination is invalid.")
    try:
        timestamp = datetime.fromisoformat(value["created_at_utc"][:-1] + "+00:00")
    except (ValueError, TypeError) as exc:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Contribution timestamp is invalid.") from exc
    if not value["created_at_utc"].endswith("Z") or timestamp.microsecond:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Contribution timestamp must be UTC seconds.")
    canonical_timestamp = timestamp.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if canonical_timestamp != value["created_at_utc"]:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Contribution timestamp is not canonical.")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if timestamp > current + timedelta(seconds=contract.MAX_FUTURE_SKEW_SECONDS):
        raise ContributionError("CONTRIBUTION_FUTURE_DATED", "Contribution timestamp exceeds allowed clock skew.")
    if current - timestamp > timedelta(seconds=MAX_APPROVAL_AGE_SECONDS):
        raise ContributionError("CONTRIBUTION_APPROVAL_EXPIRED", "Contribution approval has expired.")
    if value["content_fingerprint_sha256"] != content_fingerprint(value):
        raise ContributionError("CONTRIBUTION_FINGERPRINT_MISMATCH", "Contribution fingerprint is invalid.")
    if value["approval_id"] != approval_id(value):
        raise ContributionError("CONTRIBUTION_APPROVAL_MISMATCH", "Contribution approval ID is invalid.")
    return json.loads(_canonical(value).decode("utf-8"))


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution draft path is unsafe.")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".quality-contribution-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def prepare_contribution(proposal: Mapping[str, Any], state_dir: Path) -> dict[str, Any]:
    producer = proposal.get("producer")
    if not isinstance(producer, dict) or producer.get("owner") != "Ian-Tseng":
        raise ContributionError("CONTRIBUTION_PRODUCER_UNSUPPORTED", "Only Ian-Tseng producer proposals are eligible.")
    if proposal.get("status") != "active" or proposal.get("outbound") != "NONE":
        raise ContributionError("CONTRIBUTION_PROPOSAL_INELIGIBLE", "Only active local-only proposals are eligible.")
    if proposal.get("quality_signal") == "no_issue":
        raise ContributionError("CONTRIBUTION_PROPOSAL_INELIGIBLE", "No-issue proposals cannot be submitted.")
    destination = _destination_for_repository(producer.get("repository"))
    draft: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contribution_id": str(uuid.uuid4()),
        "proposal_id": proposal["proposal_id"],
        "receipt_digest_sha256": proposal["receipt_digest_sha256"],
        "analyzer_version": proposal["analyzer_version"],
        "producer_skill": producer["skill"],
        "producer_repository": producer["repository"],
        "producer_version": producer["version"],
        "producer_package_digest_sha256": producer["package_digest_sha256"],
        "quality_signal": proposal["quality_signal"],
        "recommended_action": proposal["recommended_action"],
        "destination": destination,
        "created_at_utc": _utc_now(),
    }
    draft["content_fingerprint_sha256"] = content_fingerprint(draft)
    draft["approval_id"] = approval_id(draft)
    validated = validate_draft(draft)
    path = Path(state_dir) / "contributions" / f"{validated['contribution_id']}.json"
    _atomic_json(path, validated)
    return {
        "status": "CONTRIBUTION_PREVIEW_READY",
        "draft": validated,
        "draft_path": str(path.resolve()),
        "approval_id": validated["approval_id"],
        "destination": validated["destination"],
        "outbound": "NONE",
        "public_visibility_confirmation_required": True,
    }


def github_title(draft: Mapping[str, Any]) -> str:
    validated = validate_draft(dict(draft))
    return f"[skill-quality] {validated['quality_signal']} from {validated['producer_skill']}"


def github_body(draft: Mapping[str, Any]) -> str:
    value = validate_draft(dict(draft))
    return (
        "## Skill quality contribution\n\n"
        f"- Schema: `{value['schema_version']}`\n"
        f"- Contribution ID: `{value['contribution_id']}`\n"
        f"- Proposal ID: `{value['proposal_id']}`\n"
        f"- Receipt digest: `{value['receipt_digest_sha256']}`\n"
        f"- Analyzer version: `{value['analyzer_version']}`\n"
        f"- Producer skill: `{value['producer_skill']}`\n"
        f"- Producer repository: `{value['producer_repository']}`\n"
        f"- Producer version: `{value['producer_version']}`\n"
        f"- Producer package digest: `{value['producer_package_digest_sha256']}`\n"
        f"- Quality signal: `{value['quality_signal']}`\n"
        f"- Recommended action: `{value['recommended_action']}`\n"
        f"- Created at: `{value['created_at_utc']}`\n"
        f"- Content fingerprint: `{value['content_fingerprint_sha256']}`\n\n"
        f"{FINAL_NOTICE}\n{AUTOMATION_NOTICE}\n"
    )


def _read_draft(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DRAFT_BYTES:
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution draft path is unsafe.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContributionError("CONTRIBUTION_SCHEMA_VIOLATION", "Contribution draft is not strict JSON.") from exc
    return validate_draft(value)


def _submission_path(draft_path: Path) -> Path:
    return draft_path.with_name(draft_path.stem + ".submission.json")


def _read_submission(path: Path, draft: Mapping[str, Any]) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DRAFT_BYTES:
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution submission state is unsafe.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution submission state is invalid.") from exc
    if not isinstance(value, dict) or set(value) != SUBMISSION_KEYS or value.get("schema_version") != 1:
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution submission state has an invalid shape.")
    if value.get("contribution_id") != draft["contribution_id"] or value.get("approval_id") != draft["approval_id"]:
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution submission state is bound to another draft.")
    if value.get("state") not in {"ATTEMPTING", "UNKNOWN", "SUBMITTED"}:
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution submission state is invalid.")
    if value.get("visibility") not in {"PUBLIC", "PRIVATE", "INTERNAL"}:
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution submission visibility is invalid.")
    issue_url = value.get("issue_url")
    if issue_url is not None and not _issue_url_pattern(draft["destination"]).fullmatch(issue_url):
        raise ContributionError("CONTRIBUTION_STATE_UNSAFE", "Contribution submission URL is invalid.")
    return value


def _claim_submission(path: Path, draft: Mapping[str, Any], visibility: str) -> tuple[dict[str, Any], bool]:
    value = {
        "schema_version": 1,
        "state": "ATTEMPTING",
        "contribution_id": draft["contribution_id"],
        "approval_id": draft["approval_id"],
        "visibility": visibility,
        "issue_url": None,
        "updated_at_utc": _utc_now(),
    }
    payload = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return _read_submission(path, draft), False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink()
        raise
    return value, True


def _finish_submission(
    path: Path,
    draft: Mapping[str, Any],
    visibility: str,
    *,
    state: str,
    issue_url: str | None,
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "state": state,
        "contribution_id": draft["contribution_id"],
        "approval_id": draft["approval_id"],
        "visibility": visibility,
        "issue_url": issue_url,
        "updated_at_utc": _utc_now(),
    }
    _atomic_json(path, value)
    return value


def _best_effort_unknown(
    path: Path,
    draft: Mapping[str, Any],
    visibility: str,
    *,
    issue_url: str | None = None,
) -> None:
    """Preserve the conservative replay barrier after a remote attempt begins."""

    with contextlib.suppress(OSError, ContributionError, TypeError, ValueError):
        _finish_submission(path, draft, visibility, state="UNKNOWN", issue_url=issue_url)


def submit_contribution(
    draft_path: Path,
    *,
    approve: str,
    approved: bool,
    allow_public_issue: bool,
    gh_command: Sequence[str] = ("gh",),
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    draft_path = Path(draft_path)
    draft = _read_draft(draft_path)
    if not approved or approve != draft["approval_id"]:
        raise ContributionError("CONTRIBUTION_APPROVAL_MISMATCH", "Exact preview approval is required.")
    submission_path = _submission_path(draft_path)
    if submission_path.exists():
        prior = _read_submission(submission_path, draft)
        if prior["state"] == "SUBMITTED":
            return {
                "status": "SUBMITTED",
                "contribution_id": draft["contribution_id"],
                "issue_url": prior["issue_url"],
                "visibility": prior["visibility"],
                "next_action": "owner_triage_then_optional_agent-ready_label",
                "newly_created": False,
            }
        raise ContributionError(
            "CONTRIBUTION_OUTCOME_UNKNOWN",
            "A prior issue-create attempt may have completed. Reconcile the contribution ID on GitHub before retrying.",
        )
    command = list(gh_command)
    if not command:
        raise ContributionError("CONTRIBUTION_DESTINATION_UNVERIFIED", "GitHub CLI command is empty.")
    if runner is subprocess.run:
        try:
            command[0] = resolve_executable(command[0])
        except ExecutableResolutionError as exc:
            raise ContributionError("CONTRIBUTION_DESTINATION_UNVERIFIED", str(exc)) from exc
    destination = draft["destination"]
    try:
        view = runner(
            [*command, "repo", "view", destination, "--json", "visibility"],
            text=True,
            capture_output=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ContributionError(
            "CONTRIBUTION_DESTINATION_UNVERIFIED",
            "GitHub repository visibility lookup timed out before issue creation.",
        ) from exc
    if view.returncode != 0:
        raise ContributionError("CONTRIBUTION_DESTINATION_UNVERIFIED", "GitHub repository visibility could not be verified.")
    try:
        visibility = json.loads(view.stdout)["visibility"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ContributionError("CONTRIBUTION_DESTINATION_UNVERIFIED", "GitHub visibility response is invalid.") from exc
    if visibility == "PUBLIC" and not allow_public_issue:
        raise ContributionError(
            "PUBLIC_ISSUE_APPROVAL_REQUIRED",
            "The exact bounded contribution will be public; a second confirmation is required.",
        )
    if visibility not in {"PUBLIC", "PRIVATE", "INTERNAL"}:
        raise ContributionError("CONTRIBUTION_DESTINATION_UNVERIFIED", "GitHub visibility is unsupported.")
    claimed, claim_created = _claim_submission(submission_path, draft, visibility)
    if claimed["state"] == "SUBMITTED":
        return {
            "status": "SUBMITTED",
            "contribution_id": draft["contribution_id"],
            "issue_url": claimed["issue_url"],
            "visibility": visibility,
            "next_action": "owner_triage_then_optional_agent-ready_label",
            "newly_created": False,
        }
    if claimed["state"] != "ATTEMPTING" or not claim_created:
        raise ContributionError(
            "CONTRIBUTION_OUTCOME_UNKNOWN",
            "A prior issue-create attempt may have completed. Reconcile the contribution ID on GitHub before retrying.",
        )
    try:
        created = runner(
            [
                *command,
                "issue",
                "create",
                "--repo",
                destination,
                "--title",
                github_title(draft),
                "--body",
                github_body(draft),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _best_effort_unknown(submission_path, draft, visibility)
        raise ContributionError(
            "CONTRIBUTION_OUTCOME_UNKNOWN",
            "GitHub issue creation did not return a confirmed outcome. Reconcile the contribution ID before retrying.",
        ) from exc
    if created.returncode != 0:
        _best_effort_unknown(submission_path, draft, visibility)
        raise ContributionError(
            "CONTRIBUTION_OUTCOME_UNKNOWN",
            "GitHub returned an error after issue creation began. Reconcile the contribution ID before retrying.",
        )
    issue_url = created.stdout.strip()
    if not _issue_url_pattern(destination).fullmatch(issue_url):
        _best_effort_unknown(submission_path, draft, visibility)
        raise ContributionError(
            "CONTRIBUTION_OUTCOME_UNKNOWN",
            "GitHub returned an unexpected response after issue creation. Reconcile the contribution ID before retrying.",
        )
    try:
        _finish_submission(submission_path, draft, visibility, state="SUBMITTED", issue_url=issue_url)
    except (OSError, ContributionError, TypeError, ValueError) as exc:
        _best_effort_unknown(submission_path, draft, visibility, issue_url=issue_url)
        raise ContributionError(
            "CONTRIBUTION_OUTCOME_UNKNOWN",
            "GitHub created an issue, but local confirmation failed. Reconcile the contribution ID before retrying.",
        ) from exc
    return {
        "status": "SUBMITTED",
        "contribution_id": draft["contribution_id"],
        "issue_url": issue_url,
        "visibility": visibility,
        "next_action": "owner_triage_then_optional_agent-ready_label",
        "newly_created": True,
    }

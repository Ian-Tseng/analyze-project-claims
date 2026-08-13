#!/usr/bin/env python3
"""Consent-gated, privacy-bounded internal problem reporting.

The reporter accepts only a small, versioned event schema. It never collects
project files, prompts, arbitrary logs, attachments, or credentials. Reports
can be delivered with the user's GitHub CLI session or to an owner HTTPS API.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib import error, parse, request


SCHEMA_VERSION = 1
POLICY_SCHEMA_VERSION = 1
PRODUCT = "analyze-project-claims"
DEFAULT_REPOSITORY = "Ian-Tseng/analyze-project-claims"
API_TOKEN_ENV = "ANALYZE_PROJECT_CLAIMS_REPORT_TOKEN"
MAX_NATIVE_OUTPUT_BYTES = 16 * 1024
MAX_API_RESPONSE_BYTES = 16 * 1024
MAX_REPORT_BYTES = 12 * 1024
MODES = {"unconfigured", "off", "ask", "auto-minimal"}
TRANSPORTS = {"github", "api"}
SEVERITIES = {"low", "medium", "high"}
EVENTS: dict[str, tuple[str, str]] = {
    "UPDATE_NATIVE_FAILURE": ("update", "medium"),
    "UPDATE_INTEGRITY_FAILURE": ("update", "high"),
    "PACKAGE_VALIDATION_FAILURE": ("package", "high"),
    "COMPONENT_MAP_INTERNAL_ERROR": ("component-map", "medium"),
    "SCAN_RECORDER_INTERNAL_ERROR": ("scan-record", "medium"),
    "REPORTER_INTERNAL_ERROR": ("reporting", "medium"),
    "REPORTING_E2E_TEST": ("reporting", "low"),
    "SKILL_RUNTIME_ERROR": ("skill-runtime", "medium"),
}
REPORT_KEYS = {
    "schema_version",
    "report_id",
    "product",
    "product_version",
    "created_at",
    "installation_id",
    "source",
    "event_code",
    "component",
    "severity",
    "summary",
    "reproduction_steps",
    "diagnostics",
    "content_fingerprint",
}
DIAGNOSTIC_KEYS = {"platform", "python_version", "gh_version", "outcome_code", "exit_code"}
POLICY_KEYS = {
    "schema_version",
    "mode",
    "transport",
    "repository",
    "endpoint",
    "installation_id",
    "last_attempt_at",
    "last_success_at",
    "last_report_id",
    "last_outcome",
}
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
OUTCOME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
RFC3339_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SENSITIVE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAuthorization\s*:\s*Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?:^|\s)[A-Za-z]:[\\/]"),
    re.compile(r"(?:^|\s)\\\\[A-Za-z0-9_.-]+[\\/]"),
    re.compile(r"(?:^|\s)/(?:Users|home|var|etc|private|mnt|tmp)/", re.IGNORECASE),
)


class ReportError(RuntimeError):
    def __init__(self, code: str, message: str, action: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


@dataclass(frozen=True)
class NativeResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class DeliveryResult:
    remote_id: str
    status: str
    url: str | None
    duplicate: bool = False
    visibility: str | None = None


def default_state_directory() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / PRODUCT if base else Path.home() / "AppData" / "Local" / PRODUCT
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / PRODUCT
    base = os.environ.get("XDG_STATE_HOME")
    return Path(base) / PRODUCT if base else Path.home() / ".local" / "state" / PRODUCT


def _uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ReportError("REPORT_INVALID", f"{field} must be a UUID string.")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ReportError("REPORT_INVALID", f"{field} must be a UUID string.") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise ReportError("REPORT_INVALID", f"{field} must be a canonical UUIDv4 string.")
    return value.lower()


def _safe_text(value: object, field: str, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise ReportError("REPORT_INVALID", f"{field} must be text.")
    text = value.strip()
    if not minimum <= len(text) <= maximum:
        raise ReportError("REPORT_INVALID", f"{field} must contain {minimum} to {maximum} characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ReportError("REPORT_REDACTION_REQUIRED", f"{field} contains control characters.")
    if any(pattern.search(text) for pattern in SENSITIVE_PATTERNS):
        raise ReportError("REPORT_REDACTION_REQUIRED", f"{field} appears to contain a credential or secret.")
    if any(pattern.search(text) for pattern in ABSOLUTE_PATH_PATTERNS):
        raise ReportError("REPORT_REDACTION_REQUIRED", f"{field} appears to contain an absolute path.")
    return text


def validate_repository(value: object) -> str:
    if not isinstance(value, str) or not REPOSITORY_PATTERN.fullmatch(value):
        raise ReportError("POLICY_INVALID", "GitHub repository must be OWNER/REPOSITORY.")
    return value


def validate_endpoint(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ReportError("POLICY_INVALID", "API transport requires an endpoint.")
    parsed = parse.urlparse(value)
    local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        parsed.scheme not in ({"https", "http"} if local else {"https"})
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ReportError("POLICY_INVALID", "Report endpoint must be an HTTPS URL without credentials or query data.")
    path = parsed.path.rstrip("/")
    if path.endswith("/v1/reports"):
        return parse.urlunparse(parsed._replace(path=path))
    if path:
        raise ReportError("POLICY_INVALID", "Report endpoint path must end in /v1/reports.")
    return parse.urlunparse(parsed._replace(path="/v1/reports"))


def default_policy() -> dict[str, object]:
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "mode": "unconfigured",
        "transport": "github",
        "repository": DEFAULT_REPOSITORY,
        "endpoint": None,
        "installation_id": str(uuid.uuid4()),
        "last_attempt_at": None,
        "last_success_at": None,
        "last_report_id": None,
        "last_outcome": "NEVER",
    }


def validate_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != POLICY_KEYS:
        raise ReportError("POLICY_INVALID", "Problem-report policy has unknown or missing fields.")
    if value["schema_version"] != POLICY_SCHEMA_VERSION or value["mode"] not in MODES:
        raise ReportError("POLICY_INVALID", "Problem-report policy version or mode is invalid.")
    if value["transport"] not in TRANSPORTS:
        raise ReportError("POLICY_INVALID", "Problem-report transport is invalid.")
    validate_repository(value["repository"])
    endpoint = value["endpoint"]
    if endpoint is not None:
        validate_endpoint(endpoint)
    if value["transport"] == "api" and endpoint is None:
        raise ReportError("POLICY_INVALID", "API transport requires an endpoint.")
    _uuid(value["installation_id"], "installation_id")
    for field in ("last_attempt_at", "last_success_at"):
        if value[field] is not None and (not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] < 0):
            raise ReportError("POLICY_INVALID", f"{field} is invalid.")
    if value["last_report_id"] is not None:
        _uuid(value["last_report_id"], "last_report_id")
    if not isinstance(value["last_outcome"], str) or not OUTCOME_PATTERN.fullmatch(value["last_outcome"]):
        raise ReportError("POLICY_INVALID", "last_outcome is invalid.")
    return dict(value)


class PolicyStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.expanduser().absolute()
        self.path = self.directory / "problem-report-policy.json"
        self.outbox = self.directory / "problem-report-outbox"
        self.receipts = self.directory / "problem-report-receipts"

    def _prepare(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ReportError("POLICY_UNSAFE", "Problem-report policy directory cannot be a symbolic link.")
        if os.name != "nt":
            os.chmod(self.directory, 0o700)

    def load(self, *, create: bool = False) -> dict[str, object]:
        if not self.path.exists():
            state = default_policy()
            if create:
                self.save(state)
            return state
        if self.path.is_symlink() or not self.path.is_file():
            raise ReportError("POLICY_UNSAFE", "Problem-report policy path is not a regular file.")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReportError("POLICY_INVALID", "Problem-report policy is not strict JSON.") from exc
        return validate_policy(value)

    def _atomic_json(self, path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
            raise ReportError("POLICY_UNSAFE", "Problem-report storage path is not a safe local directory.")
        if os.name != "nt":
            os.chmod(path.parent, 0o700)
        payload = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                os.chmod(path, 0o600)
        except Exception:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise

    def save(self, state: Mapping[str, object]) -> None:
        self._prepare()
        self._atomic_json(self.path, validate_policy(dict(state)))

    def save_report(self, report: Mapping[str, object]) -> Path:
        self._prepare()
        validated = validate_report(dict(report))
        path = self.outbox / f"{validated['report_id']}.json"
        self._atomic_json(path, validated)
        return path

    def save_receipt(self, report_id: str, value: Mapping[str, object]) -> Path:
        _uuid(report_id, "report_id")
        path = self.receipts / f"{report_id}.json"
        self._atomic_json(path, dict(value))
        return path


def package_version(skill_root: Path) -> str:
    path = skill_root / "references" / "package-version.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportError("PACKAGE_VERSION_INVALID", "Package version is unavailable.") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "skill_name", "version"}
        or value["schema_version"] != 1
        or value["skill_name"] != PRODUCT
        or not isinstance(value["version"], str)
        or not SEMVER_PATTERN.fullmatch(value["version"])
    ):
        raise ReportError("PACKAGE_VERSION_INVALID", "Package version is invalid.")
    return value["version"]


def _platform_name() -> str:
    name = platform.system().lower()
    return {"windows": "windows", "darwin": "macos", "linux": "linux"}.get(name, "other")


def _gh_version(command: Sequence[str] = ("gh",)) -> str | None:
    try:
        result = subprocess.run(
            [*command, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    match = re.search(rb"\bgh version (\d+\.\d+\.\d+)\b", result.stdout[:1024])
    return match.group(1).decode("ascii") if match and result.returncode == 0 else None


def _fingerprint_payload(report: Mapping[str, object]) -> dict[str, object]:
    return {
        key: report[key]
        for key in (
            "product",
            "product_version",
            "event_code",
            "component",
            "severity",
            "summary",
            "reproduction_steps",
            "diagnostics",
        )
    }


def report_fingerprint(report: Mapping[str, object]) -> str:
    payload = json.dumps(_fingerprint_payload(report), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_report(
    *,
    skill_root: Path,
    installation_id: str,
    event_code: str,
    summary: str,
    reproduction_steps: Sequence[str] = (),
    outcome_code: str | None = None,
    exit_code: int | None = None,
    now: Callable[[], datetime] | None = None,
    gh_command: Sequence[str] = ("gh",),
) -> dict[str, object]:
    if event_code not in EVENTS:
        raise ReportError("REPORT_INVALID", "Event code is not eligible for internal problem reporting.")
    component, severity = EVENTS[event_code]
    timestamp = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc).replace(microsecond=0)
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "report_id": str(uuid.uuid4()),
        "product": PRODUCT,
        "product_version": package_version(skill_root),
        "created_at": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "installation_id": _uuid(installation_id, "installation_id"),
        "source": "agent-detected",
        "event_code": event_code,
        "component": component,
        "severity": severity,
        "summary": summary,
        "reproduction_steps": list(reproduction_steps),
        "diagnostics": {
            "platform": _platform_name(),
            "python_version": platform.python_version(),
            "gh_version": _gh_version(gh_command),
            "outcome_code": outcome_code,
            "exit_code": exit_code,
        },
        "content_fingerprint": "0" * 64,
    }
    report["content_fingerprint"] = report_fingerprint(report)
    return validate_report(report)


def validate_report(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != REPORT_KEYS:
        raise ReportError("REPORT_INVALID", "Report has unknown or missing fields.")
    report = dict(value)
    if report["schema_version"] != SCHEMA_VERSION or report["product"] != PRODUCT:
        raise ReportError("REPORT_INVALID", "Report schema or product is invalid.")
    if not isinstance(report["product_version"], str) or not SEMVER_PATTERN.fullmatch(report["product_version"]):
        raise ReportError("REPORT_INVALID", "Report product version is invalid.")
    _uuid(report["report_id"], "report_id")
    _uuid(report["installation_id"], "installation_id")
    if not isinstance(report["created_at"], str) or not RFC3339_PATTERN.fullmatch(report["created_at"]):
        raise ReportError("REPORT_INVALID", "Report timestamp is invalid.")
    if report["source"] != "agent-detected" or report["event_code"] not in EVENTS:
        raise ReportError("REPORT_INVALID", "Report source or event code is invalid.")
    expected_component, expected_severity = EVENTS[report["event_code"]]
    if report["component"] != expected_component or report["severity"] != expected_severity:
        raise ReportError("REPORT_INVALID", "Report event classification is inconsistent.")
    report["summary"] = _safe_text(report["summary"], "summary", minimum=12, maximum=240)
    steps = report["reproduction_steps"]
    if not isinstance(steps, list) or len(steps) > 5:
        raise ReportError("REPORT_INVALID", "Report can contain at most five reproduction steps.")
    report["reproduction_steps"] = [
        _safe_text(step, f"reproduction_steps[{index}]", minimum=3, maximum=200)
        for index, step in enumerate(steps)
    ]
    diagnostics = report["diagnostics"]
    if not isinstance(diagnostics, dict) or set(diagnostics) != DIAGNOSTIC_KEYS:
        raise ReportError("REPORT_INVALID", "Report diagnostics have unknown or missing fields.")
    if diagnostics["platform"] not in {"windows", "macos", "linux", "other"}:
        raise ReportError("REPORT_INVALID", "Diagnostic platform is invalid.")
    for field in ("python_version", "gh_version"):
        item = diagnostics[field]
        if item is not None and (not isinstance(item, str) or not re.fullmatch(r"\d+\.\d+\.\d+", item)):
            raise ReportError("REPORT_INVALID", f"Diagnostic {field} is invalid.")
    outcome = diagnostics["outcome_code"]
    if outcome is not None and (not isinstance(outcome, str) or not OUTCOME_PATTERN.fullmatch(outcome)):
        raise ReportError("REPORT_INVALID", "Diagnostic outcome_code is invalid.")
    exit_code = diagnostics["exit_code"]
    if exit_code is not None and (not isinstance(exit_code, int) or isinstance(exit_code, bool) or not -255 <= exit_code <= 255):
        raise ReportError("REPORT_INVALID", "Diagnostic exit_code is invalid.")
    fingerprint = report["content_fingerprint"]
    if not isinstance(fingerprint, str) or not FINGERPRINT_PATTERN.fullmatch(fingerprint):
        raise ReportError("REPORT_INVALID", "Report fingerprint is invalid.")
    expected_fingerprint = report_fingerprint(report)
    if not hmac.compare_digest(fingerprint, expected_fingerprint):
        raise ReportError("REPORT_INVALID", "Report fingerprint does not match its content.")
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise ReportError("REPORT_INVALID", "Report exceeds the maximum encoded size.")
    return report


def load_report(path: Path) -> dict[str, object]:
    target = path.expanduser().absolute()
    if target.is_symlink() or not target.is_file():
        raise ReportError("REPORT_UNSAFE", "Report path must be a regular file and cannot be a symbolic link.")
    if target.stat().st_size > MAX_REPORT_BYTES:
        raise ReportError("REPORT_INVALID", "Report file exceeds the maximum size.")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportError("REPORT_INVALID", "Report file is not strict UTF-8 JSON.") from exc
    return validate_report(value)


def report_preview(report: Mapping[str, object]) -> dict[str, object]:
    return {
        "report_id": report["report_id"],
        "product_version": report["product_version"],
        "event_code": report["event_code"],
        "component": report["component"],
        "severity": report["severity"],
        "summary": report["summary"],
        "reproduction_steps": report["reproduction_steps"],
        "diagnostics": report["diagnostics"],
    }


def _bounded(data: bytes, limit: int) -> str:
    return data[:limit].decode("utf-8", errors="replace")


class CommandRunner:
    def run(self, arguments: Sequence[str], *, timeout: float) -> NativeResult:
        try:
            result = subprocess.run(
                list(arguments),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise ReportError("GITHUB_CLI_UNAVAILABLE", "GitHub CLI is unavailable.") from exc
        except subprocess.TimeoutExpired as exc:
            raise ReportError("DELIVERY_TIMEOUT", "Problem report delivery timed out.") from exc
        return NativeResult(
            result.returncode,
            _bounded(result.stdout, MAX_NATIVE_OUTPUT_BYTES),
            _bounded(result.stderr, MAX_NATIVE_OUTPUT_BYTES),
        )


def github_body(report: Mapping[str, object]) -> str:
    diagnostics = report["diagnostics"]
    steps = report["reproduction_steps"]
    lines = [
        "## Internal product report",
        "",
        f"- Report ID: `{report['report_id']}`",
        f"- Product version: `{report['product_version']}`",
        f"- Event: `{report['event_code']}`",
        f"- Component: `{report['component']}`",
        f"- Severity: `{report['severity']}`",
        f"- Platform: `{diagnostics['platform']}`",
        f"- Python: `{diagnostics['python_version']}`",
        f"- GitHub CLI: `{diagnostics['gh_version'] or 'unavailable'}`",
        f"- Outcome: `{diagnostics['outcome_code'] or 'not-provided'}`",
        f"- Exit code: `{diagnostics['exit_code'] if diagnostics['exit_code'] is not None else 'not-provided'}`",
        f"- Fingerprint: `{report['content_fingerprint']}`",
        "",
        "## Summary",
        "",
        str(report["summary"]),
    ]
    if steps:
        lines.extend(["", "## Reproduction"])
        lines.extend(f"{index}. {step}" for index, step in enumerate(steps, 1))
    lines.extend(
        [
            "",
            "This report uses the bounded internal-event schema. It does not include attachments, raw logs, prompts, or project files.",
            "",
        ]
    )
    return "\n".join(lines)


class GitHubTransport:
    def __init__(self, repository: str, *, command: Sequence[str] = ("gh",), runner: CommandRunner | None = None) -> None:
        self.repository = validate_repository(repository)
        self.command = list(command)
        self.runner = runner or CommandRunner()

    def repository_visibility(self) -> str:
        result = self.runner.run(
            [*self.command, "repo", "view", self.repository, "--json", "visibility", "--jq", ".visibility"],
            timeout=20,
        )
        visibility = result.stdout.strip().lower()
        if result.returncode != 0 or visibility not in {"private", "internal", "public"}:
            raise ReportError(
                "DELIVERY_VISIBILITY_UNKNOWN",
                "GitHub repository visibility could not be verified; no issue was created.",
                action="Check GitHub CLI access and retry. Use the owner API when private delivery is required.",
            )
        return visibility

    def send(self, report: Mapping[str, object], *, allow_public_issue: bool = False) -> DeliveryResult:
        validated = validate_report(dict(report))
        visibility = self.repository_visibility()
        if visibility == "public" and not allow_public_issue:
            raise ReportError(
                "PUBLIC_ISSUE_APPROVAL_REQUIRED",
                "The target repository is public; no issue was created.",
                action=(
                    "Review the bounded preview and rerun submit with both --approved and "
                    "--allow-public-issue, or configure the private owner API."
                ),
            )
        descriptor, name = tempfile.mkstemp(prefix="problem-report-", suffix=".md")
        path = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(github_body(validated))
            title = f"[internal-report] {validated['event_code']}: {validated['summary']}"
            if len(title) > 240:
                title = title[:237] + "..."
            result = self.runner.run(
                [*self.command, "issue", "create", "--repo", self.repository, "--title", title, "--body-file", str(path)],
                timeout=20,
            )
        finally:
            with contextlib.suppress(OSError):
                path.unlink()
        if result.returncode != 0:
            raise ReportError("DELIVERY_FAILED", "GitHub CLI could not create the issue.")
        url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        expected = re.compile(rf"^https://github\.com/{re.escape(self.repository)}/issues/(\d+)$", re.IGNORECASE)
        match = expected.fullmatch(url)
        if not match:
            raise ReportError("DELIVERY_INVALID_RESPONSE", "GitHub CLI returned an unexpected issue URL.")
        return DeliveryResult(match.group(1), "received", url, visibility=visibility)


class ApiTransport:
    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        opener: Callable[..., object] | None = None,
    ) -> None:
        self.endpoint = validate_endpoint(endpoint)
        self.token = token if token is not None else os.environ.get(API_TOKEN_ENV)
        self.opener = opener or request.urlopen

    def _request(self, method: str, url: str, payload: object | None = None) -> dict[str, object]:
        if not self.token or len(self.token) < 20 or len(self.token) > 512 or re.search(r"\s", self.token):
            raise ReportError("API_TOKEN_UNAVAILABLE", f"Set a scoped client token in {API_TOKEN_ENV}.")
        data = None if payload is None else json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        outbound = request.Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener(outbound, timeout=20) as response:
                raw = response.read(MAX_API_RESPONSE_BYTES + 1)
        except error.HTTPError as exc:
            raise ReportError("DELIVERY_FAILED", f"Report API rejected the request with HTTP {exc.code}.") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ReportError("DELIVERY_FAILED", "Report API is unavailable.") from exc
        if len(raw) > MAX_API_RESPONSE_BYTES:
            raise ReportError("DELIVERY_INVALID_RESPONSE", "Report API response is too large.")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReportError("DELIVERY_INVALID_RESPONSE", "Report API returned invalid JSON.") from exc
        if not isinstance(value, dict):
            raise ReportError("DELIVERY_INVALID_RESPONSE", "Report API returned the wrong JSON shape.")
        return value

    def send(self, report: Mapping[str, object]) -> DeliveryResult:
        validated = validate_report(dict(report))
        value = self._request("POST", self.endpoint, validated)
        remote_id = value.get("report_id")
        status = value.get("status")
        duplicate = value.get("duplicate", False)
        if (
            not isinstance(remote_id, str)
            or status not in {"received", "triaged", "fixed", "closed", "rejected"}
            or not isinstance(duplicate, bool)
            or (not duplicate and remote_id != validated["report_id"])
        ):
            raise ReportError("DELIVERY_INVALID_RESPONSE", "Report API response identity or status is invalid.")
        _uuid(remote_id, "report_id")
        return DeliveryResult(remote_id, status, f"{self.endpoint}/{remote_id}", duplicate)

    def delete(self, report_id: str) -> DeliveryResult:
        canonical = _uuid(report_id, "report_id")
        value = self._request("DELETE", f"{self.endpoint}/{canonical}")
        if value.get("report_id") != canonical or value.get("status") != "deleted":
            raise ReportError("DELIVERY_INVALID_RESPONSE", "Report API deletion response is invalid.")
        return DeliveryResult(canonical, "deleted", None)

    def status(self, report_id: str) -> DeliveryResult:
        canonical = _uuid(report_id, "report_id")
        value = self._request("GET", f"{self.endpoint}/{canonical}")
        if value.get("report_id") != canonical or value.get("status") not in {"received", "triaged", "fixed", "closed", "rejected"}:
            raise ReportError("DELIVERY_INVALID_RESPONSE", "Report API status response is invalid.")
        return DeliveryResult(canonical, str(value["status"]), f"{self.endpoint}/{canonical}")


def _result(status: str, state: Mapping[str, object], message: str, **extra: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "status": status,
        "mode": state["mode"],
        "transport": state["transport"],
        "message": message,
        "action": None,
    }
    value.update(extra)
    return value


class Reporter:
    def __init__(
        self,
        skill_root: Path,
        store: PolicyStore,
        *,
        gh_command: Sequence[str] = ("gh",),
        github_factory: Callable[[str], object] | None = None,
        api_factory: Callable[[str], object] | None = None,
        now_epoch: Callable[[], float] = time.time,
    ) -> None:
        self.skill_root = skill_root.resolve()
        self.store = store
        self.gh_command = list(gh_command)
        self.github_factory = github_factory or (lambda repository: GitHubTransport(repository, command=self.gh_command))
        self.api_factory = api_factory or (lambda endpoint: ApiTransport(endpoint))
        self.now_epoch = now_epoch

    def configure(
        self,
        mode: str,
        *,
        transport: str | None = None,
        repository: str | None = None,
        endpoint: str | None = None,
    ) -> dict[str, object]:
        if mode not in {"ask", "auto-minimal", "off"}:
            raise ReportError("POLICY_INVALID", "Configure mode must be ask, auto-minimal, or off.")
        state = self.store.load(create=True)
        selected_transport = transport or str(state["transport"])
        if selected_transport not in TRANSPORTS:
            raise ReportError("POLICY_INVALID", "Problem-report transport is invalid.")
        if mode == "auto-minimal" and selected_transport == "github":
            raise ReportError(
                "PRIVATE_TRANSPORT_REQUIRED",
                "Automatic problem reporting requires the private owner API.",
                action=(
                    "Configure ask mode for user-approved GitHub issues, or configure auto-minimal "
                    "with the owner API endpoint."
                ),
            )
        state["mode"] = mode
        state["transport"] = selected_transport
        if repository is not None:
            state["repository"] = validate_repository(repository)
        if endpoint is not None:
            state["endpoint"] = validate_endpoint(endpoint)
        if selected_transport == "api" and state["endpoint"] is None:
            raise ReportError("POLICY_INVALID", "API transport requires --endpoint.")
        state["last_outcome"] = "CONFIGURED"
        self.store.save(state)
        return _result("CONFIGURED", state, f"Problem reporting is {mode} through {selected_transport}.")

    def status(self) -> dict[str, object]:
        state = self.store.load()
        return _result(
            "STATUS",
            state,
            f"Problem reporting is {state['mode']} through {state['transport']}.",
            report_schema_version=SCHEMA_VERSION,
            repository=state["repository"],
            endpoint=state["endpoint"],
            last_report_id=state["last_report_id"],
            last_outcome=state["last_outcome"],
        )

    def prepare(
        self,
        *,
        event_code: str,
        summary: str,
        reproduction_steps: Sequence[str] = (),
        outcome_code: str | None = None,
        exit_code: int | None = None,
    ) -> dict[str, object]:
        state = self.store.load(create=True)
        report = build_report(
            skill_root=self.skill_root,
            installation_id=str(state["installation_id"]),
            event_code=event_code,
            summary=summary,
            reproduction_steps=reproduction_steps,
            outcome_code=outcome_code,
            exit_code=exit_code,
            gh_command=self.gh_command,
        )
        path = self.store.save_report(report)
        consent_required = state["mode"] in {"unconfigured", "ask", "off"}
        action = (
            "Review the preview, then run submit --approved for this report. "
            "Use configure --mode ask or configure --mode auto-minimal to set a persistent policy."
            if consent_required
            else "Run submit; auto-minimal consent is already configured."
        )
        return _result(
            "REPORT_PREPARED",
            state,
            "A bounded internal problem report was prepared locally. Nothing was sent.",
            action=action,
            report_path=str(path),
            consent_required=consent_required,
            preview=report_preview(report),
        )

    def _transport(self, state: Mapping[str, object]):
        if state["transport"] == "github":
            return self.github_factory(str(state["repository"]))
        endpoint = state["endpoint"]
        if not isinstance(endpoint, str):
            raise ReportError("POLICY_INVALID", "API transport requires an endpoint.")
        return self.api_factory(endpoint)

    def submit(
        self,
        report_path: Path,
        *,
        approved: bool = False,
        allow_public_issue: bool = False,
    ) -> dict[str, object]:
        state = self.store.load(create=True)
        report = load_report(report_path)
        if report["installation_id"] != state["installation_id"]:
            raise ReportError("REPORT_IDENTITY_MISMATCH", "Report belongs to a different local installation.")
        if state["mode"] == "auto-minimal" and state["transport"] == "github":
            raise ReportError(
                "PRIVATE_TRANSPORT_REQUIRED",
                "A legacy automatic GitHub policy was stopped before delivery.",
                action=(
                    "Reconfigure ask mode for user-approved GitHub issues, or configure auto-minimal "
                    "with the private owner API."
                ),
            )
        if state["mode"] != "auto-minimal" and not approved:
            return _result(
                "CONSENT_REQUIRED" if state["mode"] != "off" else "REPORTING_DISABLED",
                state,
                "Explicit approval is required before this report can leave the device.",
                action="Review the report preview and rerun submit with --approved for this report only.",
                preview=report_preview(report),
            )
        if allow_public_issue and (
            state["transport"] != "github" or not approved or state["mode"] == "auto-minimal"
        ):
            raise ReportError(
                "PUBLIC_ISSUE_APPROVAL_INVALID",
                "Public-issue approval is valid only for an explicitly approved GitHub report.",
            )
        state["last_attempt_at"] = max(0, int(self.now_epoch()))
        state["last_report_id"] = report["report_id"]
        try:
            transport = self._transport(state)
            if state["transport"] == "github":
                delivered = transport.send(report, allow_public_issue=allow_public_issue)
            else:
                delivered = transport.send(report)
        except ReportError:
            state["last_outcome"] = "DELIVERY_FAILED"
            self.store.save(state)
            raise
        state["last_success_at"] = state["last_attempt_at"]
        state["last_outcome"] = "REPORT_SENT"
        self.store.save(state)
        receipt = {
            "schema_version": 1,
            "report_id": report["report_id"],
            "transport": state["transport"],
            "remote_id": delivered.remote_id,
            "status": delivered.status,
            "url": delivered.url,
            "duplicate": delivered.duplicate,
            "visibility": delivered.visibility,
            "delivered_at": state["last_success_at"],
        }
        receipt_path = self.store.save_receipt(str(report["report_id"]), receipt)
        return _result(
            "REPORT_SENT",
            state,
            "The bounded internal problem report was delivered.",
            report_id=report["report_id"],
            remote_id=delivered.remote_id,
            remote_status=delivered.status,
            url=delivered.url,
            duplicate=delivered.duplicate,
            visibility=delivered.visibility,
            receipt_path=str(receipt_path),
        )

    def remote_status(self, report_id: str) -> dict[str, object]:
        state = self.store.load()
        if state["transport"] != "api":
            raise ReportError("STATUS_UNAVAILABLE", "Remote status lookup is available for API transport only.")
        delivered = self._transport(state).status(report_id)
        return _result(
            "REMOTE_STATUS",
            state,
            f"Remote report status is {delivered.status}.",
            report_id=delivered.remote_id,
            remote_status=delivered.status,
            url=delivered.url,
        )

    def remote_delete(self, report_id: str) -> dict[str, object]:
        state = self.store.load()
        if state["transport"] != "api":
            raise ReportError("DELETE_UNAVAILABLE", "Remote deletion is available for API transport only.")
        delivered = self._transport(state).delete(report_id)
        return _result(
            "REMOTE_DELETED",
            state,
            "The owner API deleted this installation's report.",
            report_id=delivered.remote_id,
            remote_status=delivered.status,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and deliver bounded internal problem reports.")
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-dir", type=Path, default=default_state_directory())
    parser.add_argument("--gh", default="gh", help="GitHub CLI executable.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure")
    configure.add_argument("--mode", choices=("ask", "auto-minimal", "off"), required=True)
    configure.add_argument("--transport", choices=("github", "api"))
    configure.add_argument("--repository")
    configure.add_argument("--endpoint")
    commands.add_parser("status")
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--event-code", choices=tuple(EVENTS), required=True)
    prepare_parser.add_argument("--summary", required=True)
    prepare_parser.add_argument("--step", action="append", default=[])
    prepare_parser.add_argument("--outcome-code")
    prepare_parser.add_argument("--exit-code", type=int)
    submit = commands.add_parser("submit")
    submit.add_argument("--report", type=Path, required=True)
    submit.add_argument("--approved", action="store_true")
    submit.add_argument(
        "--allow-public-issue",
        action="store_true",
        help="Allow this explicitly approved bounded report to become a public GitHub issue.",
    )
    remote = commands.add_parser("remote-status")
    remote.add_argument("--report-id", required=True)
    delete = commands.add_parser("remote-delete")
    delete.add_argument("--report-id", required=True)
    return parser


def _render(result: Mapping[str, object]) -> str:
    lines = [f"{result['status']}: {result['message']}"]
    if result.get("action"):
        lines.append(f"Action: {result['action']}")
    if result.get("report_path"):
        lines.append(f"Local report: {result['report_path']}")
    if result.get("url"):
        lines.append(f"Remote: {result['url']}")
    if result.get("preview"):
        lines.extend(["Preview:", json.dumps(result["preview"], indent=2, sort_keys=True, ensure_ascii=False)])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    reporter = Reporter(args.skill_root, PolicyStore(args.state_dir), gh_command=(args.gh,))
    try:
        if args.command == "configure":
            result = reporter.configure(
                args.mode,
                transport=args.transport,
                repository=args.repository,
                endpoint=args.endpoint,
            )
        elif args.command == "status":
            result = reporter.status()
        elif args.command == "prepare":
            result = reporter.prepare(
                event_code=args.event_code,
                summary=args.summary,
                reproduction_steps=args.step,
                outcome_code=args.outcome_code,
                exit_code=args.exit_code,
            )
        elif args.command == "submit":
            result = reporter.submit(
                args.report,
                approved=args.approved,
                allow_public_issue=args.allow_public_issue,
            )
        elif args.command == "remote-status":
            result = reporter.remote_status(args.report_id)
        elif args.command == "remote-delete":
            result = reporter.remote_delete(args.report_id)
        else:
            parser.error("Unknown command")
            return 2
    except ReportError as exc:
        state = default_policy()
        with contextlib.suppress(ReportError):
            state = reporter.store.load()
        result = _result(exc.code, state, exc.message, action=exc.action)
        output = json.dumps(result, sort_keys=True, ensure_ascii=False) if args.format == "json" else _render(result)
        print(output, file=sys.stderr)
        return 3
    output = json.dumps(result, sort_keys=True, ensure_ascii=False) if args.format == "json" else _render(result)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

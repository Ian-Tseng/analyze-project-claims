"""Versioned evidence-bound scan records for analyze-project-claims."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import mimetypes
import os
import re
import stat
import tempfile
import unicodedata
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence
from urllib.parse import quote, urlsplit

from _internal.component_evidence.identity import (
    EngineIdentityError,
    verified_engine_summary,
)


SCHEMA_VERSION = "2.0"
RECORDER_VERSION = "2.0.0"
RECORD_KIND = "evidence_bound_audit_record"
RENDERER_ID = "evidence-bound-markdown-v1"
COMMANDS = {
    "preflight",
    "init",
    "evidence",
    "validate",
    "append",
    "render",
    "verify",
    "draft-v2",
}
ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[-:.][a-z0-9]+)*$")
MAP_ID_PATTERN = re.compile(r"^component-map-[0-9a-f]{12}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(
        r"\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)"
        r"\s*[:=]\s*[^\s,;]{8,}",
        re.IGNORECASE,
    ),
)
METHODS = {
    "inspected",
    "schema_validated",
    "executed_test",
    "replayed",
    "inferred",
    "not_tested",
}
CLAIM_STATUSES = {
    "supported",
    "partially_supported",
    "contradicted",
    "untested",
    "invalidly_specified",
    "not_applicable",
}
ROLES = {"supports", "contradicts", "limits", "context"}
LOCATOR_KINDS = {"whole_file", "json_pointer", "line_range", "test_case", "artifact_key"}
CURRENT_FRESHNESS = {"current", "declared_immutable"}
MAX_CLAIMS = 200
MAX_EVIDENCE = 300
MAX_BINDINGS = 1000
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_SELECTION_BYTES = 64 * 1024
MAX_OBSERVATION_CHARS = 2000
MAX_RENDER_BYTES = 1024 * 1024
DOC_URL = (
    "https://github.com/Ian-Tseng/analyze-project-claims/blob/main/"
    "skills/analyze-project-claims/references/evidence-bound-audit-records.md"
)


class AuditRecordError(ValueError):
    """A stable, actionable v2 contract failure."""

    def __init__(
        self,
        code: str,
        problem: str,
        cause: str,
        effect: str,
        fix: str,
        *,
        retry: str = "Rerun the same command after applying the fix.",
    ) -> None:
        super().__init__(problem)
        self.code = code
        self.problem = problem
        self.cause = cause
        self.effect = effect
        self.fix = fix
        self.retry = retry

    def __str__(self) -> str:
        anchor = self.code.lower().replace("_", "-")
        return "\n".join(
            [
                self.code,
                "",
                f"Problem: {self.problem}",
                f"Cause: {self.cause}",
                f"Effect: {self.effect}",
                f"Fix: {self.fix}",
                f"Retry: {self.retry}",
                f"Docs: {DOC_URL}#{anchor}",
            ]
        )


def _raise(
    code: str,
    problem: str,
    cause: str,
    effect: str,
    fix: str,
    *,
    retry: str = "Rerun the same command after applying the fix.",
) -> None:
    raise AuditRecordError(code, problem, cause, effect, fix, retry=retry)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, code: str = "RECORD_JSON_INVALID") -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _raise(
            code,
            f"Cannot read valid JSON from {path}.",
            str(exc),
            "No record was validated or changed.",
            "Repair the JSON or provide the correct file path.",
        )
    if not isinstance(value, dict):
        _raise(
            code,
            f"{path} does not contain a JSON object.",
            "The top-level JSON value has the wrong type.",
            "No record was validated or changed.",
            "Use an object as the top-level value.",
        )
    return value


def _reject_unknown(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _raise(
            "RECORD_SCHEMA_UNSUPPORTED",
            f"{field} contains unsupported fields: {', '.join(unknown)}.",
            "The input does not match the closed v2 contract.",
            "The record cannot be validated or appended.",
            "Remove the fields or use a schema version that defines them.",
        )


def _text(value: Any, field: str, *, maximum: int = MAX_OBSERVATION_CHARS) -> str:
    if not isinstance(value, str) or not value.strip():
        _raise(
            "RECORD_SCHEMA_UNSUPPORTED",
            f"{field} must be a non-empty string.",
            "A required text value is missing or empty.",
            "The record cannot be validated or appended.",
            f"Provide a non-empty {field} value.",
        )
    result = value.strip()
    unsafe_unicode = any(
        unicodedata.category(char) in {"Cc", "Cf", "Cs"} and char not in "\n\t"
        for char in result
    )
    if len(result) > maximum or unsafe_unicode:
        _raise(
            "RECORD_TEXT_UNSAFE",
            f"{field} is oversized or contains an unsafe Unicode control or format character.",
            f"Text is limited to {maximum} characters and excludes control, format, surrogate, and bidi-control code points.",
            "The value cannot be safely persisted or rendered.",
            "Use bounded plain text without terminal, bidi, or invisible format controls.",
        )
    return result


def _safe_observation(value: Any, field: str) -> str:
    text = _text(value, field)
    if any(pattern.search(text) for pattern in SECRET_PATTERNS):
        _raise(
            "SENSITIVE_OBSERVATION_REJECTED",
            f"{field} appears to contain a credential or private key.",
            "Evidence-bound records are durable artifacts and must not persist secret-like values.",
            "The record was rejected before evidence materialization or writing.",
            "Redact the value and record only a non-sensitive observation summary.",
        )
    return text


def _looks_like_test_source(source: dict[str, Any]) -> bool:
    if source.get("kind") != "file":
        return False
    path = PurePosixPath(source["path"])
    name = path.name.lower()
    source_suffixes = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".rb", ".go", ".rs", ".java", ".kt", ".swift"}
    under_test_tree = any(part.lower() in {"test", "tests", "spec", "specs"} for part in path.parts[:-1])
    named_test = name.startswith("test_") or any(name.endswith(f"_test{suffix}") for suffix in source_suffixes)
    return path.suffix.lower() in source_suffixes and (under_test_tree or named_test)


def _text_list(value: Any, field: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        _raise(
            "RECORD_SCHEMA_UNSUPPORTED",
            f"{field} must be {'a non-empty' if nonempty else 'an'} array of strings.",
            "The input has the wrong collection shape.",
            "The record cannot be validated or appended.",
            f"Provide the required {field} array.",
        )
    return [_text(item, f"{field}[{index}]") for index, item in enumerate(value)]


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field, maximum=128)
    if ID_PATTERN.fullmatch(result) is None:
        _raise(
            "RECORD_SCHEMA_UNSUPPORTED",
            f"{field} has an invalid stable identifier: {result!r}.",
            "Identifiers must be lowercase ASCII slugs separated by '-', ':', or '.'.",
            "References and deterministic rendering would be ambiguous.",
            "Choose an identifier such as claim:release-ready or evidence:test-suite.",
        )
    return result


def _relative_posix_path(value: Any, field: str) -> str:
    text = _text(value, field, maximum=500)
    path = PurePosixPath(text)
    unsafe = (
        path.is_absolute()
        or ".." in path.parts
        or text != path.as_posix()
        or "\\" in text
        or not path.parts
        or any(part in {"", "."} for part in path.parts)
        or any(ord(char) < 32 for char in text)
    )
    if unsafe:
        _raise(
            "EVIDENCE_PATH_UNSAFE",
            f"{field} is not a safe project-root-relative POSIX path: {text!r}.",
            "Absolute paths, traversal, backslashes, empty segments, and controls are forbidden.",
            "The evidence artifact will not be read.",
            "Use a normalized path such as results/run-1.json.",
        )
    return text


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_file(project_root: Path, relative: str) -> Path:
    root = project_root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    cursor = root
    for part in PurePosixPath(relative).parts:
        cursor = cursor / part
        if cursor.exists() and (cursor.is_symlink() or _is_reparse(cursor)):
            _raise(
                "EVIDENCE_PATH_UNSAFE",
                f"Evidence path {relative!r} crosses a symlink or reparse point.",
                f"Unsafe path component: {cursor}.",
                "The evidence artifact will not be read.",
                "Use an ordinary file contained directly by the project root.",
            )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        _raise(
            "EVIDENCE_PATH_UNSAFE",
            f"Evidence path {relative!r} is missing or escapes the project root.",
            str(exc),
            "The evidence artifact will not be read.",
            "Use an existing ordinary file inside the declared project root.",
        )
    if not resolved.is_file():
        _raise(
            "EVIDENCE_PATH_UNSAFE",
            f"Evidence path {relative!r} is not an ordinary file.",
            "Directory and device evidence are not accepted implicitly.",
            "The evidence artifact will not be read.",
            "Point to a bounded manifest or receipt file instead.",
        )
    return resolved


def _read_stable(path: Path) -> bytes:
    before = path.stat()
    if before.st_size > MAX_SOURCE_BYTES:
        _raise(
            "EVIDENCE_SOURCE_TOO_LARGE",
            f"Evidence source {path.name!r} exceeds {MAX_SOURCE_BYTES} bytes.",
            "The v2 contract bounds source reads.",
            "The artifact cannot be evidence-bound by this command.",
            "Create a bounded manifest or receipt that identifies the larger artifact.",
        )
    data = path.read_bytes()
    after = path.stat()
    identity_before = (before.st_size, before.st_mtime_ns, getattr(before, "st_ino", None))
    identity_after = (after.st_size, after.st_mtime_ns, getattr(after, "st_ino", None))
    if identity_before != identity_after or len(data) != after.st_size:
        _raise(
            "EVIDENCE_CHANGED_DURING_READ",
            f"Evidence source {path.name!r} changed while it was being hashed.",
            "Stable file metadata differed before and after the read.",
            "No record was appended.",
            "Stop the writer or snapshot the artifact, then retry.",
        )
    if data.startswith(b"version https://git-lfs.github.com/spec/v1"):
        _raise(
            "EVIDENCE_SOURCE_UNAVAILABLE",
            f"Evidence source {path.name!r} is a Git LFS pointer, not the artifact bytes.",
            "The referenced large-file object is not present in the working tree.",
            "The pointer cannot support a claim about the missing artifact content.",
            "Fetch the LFS object or cite a bounded persisted receipt for it.",
        )
    return data


def _json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        _raise(
            "EVIDENCE_LOCATOR_UNSUPPORTED",
            f"JSON Pointer {pointer!r} must be empty or start with '/'.",
            "The locator is not RFC 6901-shaped.",
            "The selected evidence cannot be identified.",
            "Use a pointer such as /results/accuracy.",
        )
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, list):
                current = current[int(token)]
            elif isinstance(current, dict):
                current = current[token]
            else:
                raise KeyError(token)
        except (KeyError, IndexError, ValueError) as exc:
            _raise(
                "EVIDENCE_LOCATOR_MISSING",
                f"JSON Pointer {pointer!r} does not resolve.",
                f"Missing token: {token!r}.",
                "The evidence selection cannot be bound.",
                "Correct the pointer or refresh the artifact.",
            )
    return current


def _normalize_locator(raw: Any, field: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _raise(
            "EVIDENCE_LOCATOR_UNSUPPORTED",
            f"{field} must be an object.",
            "The locator has the wrong type.",
            "The evidence selection cannot be bound.",
            "Use a typed locator object.",
        )
    kind = _text(raw.get("kind"), f"{field}.kind", maximum=40)
    if kind not in LOCATOR_KINDS:
        _raise(
            "EVIDENCE_LOCATOR_UNSUPPORTED",
            f"{field}.kind is unsupported: {kind!r}.",
            f"Supported kinds are: {', '.join(sorted(LOCATOR_KINDS))}.",
            "The evidence selection cannot be bound.",
            "Choose one supported typed locator.",
        )
    if kind == "whole_file":
        _reject_unknown(raw, {"kind"}, field)
        return {"kind": kind}
    if kind == "line_range":
        _reject_unknown(raw, {"kind", "start", "end"}, field)
        start, end = raw.get("start"), raw.get("end")
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start < 1 or end < start:
            _raise(
                "EVIDENCE_LOCATOR_UNSUPPORTED",
                f"{field} has an invalid one-based line range.",
                "start and end must be integers with 1 <= start <= end.",
                "The evidence selection cannot be bound.",
                "Provide a valid inclusive line range.",
            )
        return {"kind": kind, "start": start, "end": end}
    _reject_unknown(raw, {"kind", "value"}, field)
    value = _text(raw.get("value"), f"{field}.value", maximum=500)
    return {"kind": kind, "value": value}


def _select_bytes(data: bytes, locator: dict[str, Any], source: str) -> bytes:
    kind = locator["kind"]
    if kind == "whole_file":
        selected = data
    elif kind in {"json_pointer", "artifact_key"}:
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _raise(
                "EVIDENCE_LOCATOR_MISSING",
                f"Evidence source {source!r} is not valid UTF-8 JSON.",
                str(exc),
                "The declared structured locator cannot resolve.",
                "Use a JSON artifact or a different locator kind.",
            )
        if kind == "json_pointer":
            selected_value = _json_pointer(value, locator["value"])
        else:
            key = locator["value"]
            if not isinstance(value, dict) or key not in value:
                _raise(
                    "EVIDENCE_LOCATOR_MISSING",
                    f"Artifact key {key!r} does not resolve in {source!r}.",
                    "The JSON artifact has no matching top-level key.",
                    "The evidence selection cannot be bound.",
                    "Correct the artifact key or refresh the artifact.",
                )
            selected_value = value[key]
        selected = _canonical_bytes(selected_value)
    elif kind == "line_range":
        lines = data.splitlines(keepends=True)
        start, end = locator["start"], locator["end"]
        if end > len(lines):
            _raise(
                "EVIDENCE_LOCATOR_MISSING",
                f"Line range {start}-{end} exceeds {source!r}, which has {len(lines)} lines.",
                "The artifact no longer has the declared line span.",
                "The evidence selection cannot be bound.",
                "Correct the range or refresh the artifact.",
            )
        selected = b"".join(lines[start - 1 : end])
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            _raise(
                "EVIDENCE_LOCATOR_MISSING",
                f"Test-case locator cannot decode {source!r} as UTF-8.",
                str(exc),
                "The test receipt selection cannot be bound.",
                "Use a UTF-8 execution receipt or a different locator.",
            )
        matches = [line for line in text.splitlines(keepends=True) if locator["value"] in line]
        if not matches:
            _raise(
                "EVIDENCE_LOCATOR_MISSING",
                f"Test case {locator['value']!r} does not appear in {source!r}.",
                "The execution receipt has no matching test identifier.",
                "The evidence selection cannot be bound.",
                "Use the exact persisted test identifier.",
            )
        selected = "".join(matches).encode("utf-8")
    if len(selected) > MAX_SELECTION_BYTES:
        _raise(
            "EVIDENCE_SELECTION_TOO_LARGE",
            f"The selected evidence in {source!r} exceeds {MAX_SELECTION_BYTES} bytes.",
            "Rendered and persisted evidence selections are bounded.",
            "The evidence item cannot be appended.",
            "Use a narrower locator or a compact receipt.",
        )
    return selected


def _validate_https_source(raw: dict[str, Any], field: str) -> dict[str, Any]:
    _reject_unknown(raw, {"kind", "url", "revision", "sha256"}, field)
    url = _text(raw.get("url"), f"{field}.url", maximum=1000)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        _raise(
            "EXTERNAL_EVIDENCE_UNSAFE",
            f"External evidence URL {url!r} is not a safe query-free HTTPS URL.",
            "Only HTTPS URLs without credentials, query strings, or fragments are accepted.",
            "The external evidence item cannot be recorded.",
            "Use a public immutable URL and put selection details in the locator.",
        )
    result: dict[str, Any] = {"kind": "https", "url": url}
    revision = raw.get("revision")
    digest = raw.get("sha256")
    if revision is not None:
        result["revision"] = _text(revision, f"{field}.revision", maximum=300)
    if digest is not None:
        digest_text = _text(digest, f"{field}.sha256", maximum=64)
        if SHA256_PATTERN.fullmatch(digest_text) is None:
            _raise(
                "RECORD_SCHEMA_UNSUPPORTED",
                f"{field}.sha256 is not a lowercase SHA-256 digest.",
                "External artifact digests use 64 lowercase hexadecimal characters.",
                "The external identity cannot be trusted.",
                "Provide the exact SHA-256 digest or omit it and accept unverifiable status.",
            )
        result["sha256"] = digest_text
    return result


def _normalize_source(raw: Any, field: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _raise(
            "RECORD_SCHEMA_UNSUPPORTED",
            f"{field} must be an object.",
            "The evidence source has the wrong type.",
            "The evidence item cannot be validated.",
            "Use a typed file or HTTPS source object.",
        )
    kind = raw.get("kind")
    if kind == "file":
        _reject_unknown(raw, {"kind", "path"}, field)
        return {"kind": "file", "path": _relative_posix_path(raw.get("path"), f"{field}.path")}
    if kind == "https":
        return _validate_https_source(raw, field)
    _raise(
        "RECORD_SCHEMA_UNSUPPORTED",
        f"{field}.kind must be 'file' or 'https'.",
        f"Unsupported source kind: {kind!r}.",
        "The evidence item cannot be validated.",
        "Choose one supported source kind.",
    )


def _load_map(map_root: Path, project_root: Path, skill_root: Path) -> dict[str, Any]:
    project = project_root.resolve(strict=True)
    map_path = (map_root / "accepted-map.json").resolve(strict=True)
    try:
        relative_map = map_path.relative_to(project).as_posix()
    except ValueError:
        _raise(
            "MAP_NOT_ACCEPTED",
            "The accepted map is outside the project root.",
            f"Resolved map path: {map_path}.",
            "The scan cannot bind to this map.",
            "Place the accepted map under the project root.",
        )
    if map_path.is_symlink() or _is_reparse(map_path):
        _raise(
            "MAP_NOT_ACCEPTED",
            "The accepted map is a symlink or reparse point.",
            "Map identity must resolve to an ordinary local file.",
            "The scan cannot bind to this map.",
            "Use an ordinary accepted-map.json file.",
        )
    value = _load_json(map_path, "MAP_NOT_ACCEPTED")
    map_id = value.get("map_id")
    if (
        value.get("map_state") != "accepted"
        or value.get("skill_name") != "analyze-project-claims"
        or not isinstance(map_id, str)
        or MAP_ID_PATTERN.fullmatch(map_id) is None
    ):
        _raise(
            "MAP_NOT_ACCEPTED",
            "accepted-map.json is not an accepted analyze-project-claims map with a semantic map ID.",
            "The map state, skill name, or component-map identity is invalid.",
            "No v2 record can be validated or appended.",
            "Reconcile and explicitly accept a component-map candidate first.",
        )
    integrity = value.get("integrity")
    expected = integrity.get("canonical_payload_sha256") if isinstance(integrity, dict) else None
    payload = copy.deepcopy(value)
    payload.pop("integrity", None)
    if not isinstance(expected, str) or _sha256_bytes(_canonical_bytes(payload)) != expected:
        _raise(
            "MAP_IDENTITY_MISMATCH",
            "accepted-map.json fails its canonical integrity check.",
            "The persisted map payload does not match its integrity digest.",
            "No v2 record can bind to this map.",
            "Restore or explicitly replace the accepted map through reconciliation.",
        )
    skill_sha = _sha256_file(skill_root / "SKILL.md")
    if value.get("skill_sha256") != skill_sha:
        _raise(
            "MAP_IDENTITY_MISMATCH",
            "The accepted map was produced for different skill instructions.",
            "accepted-map.json skill_sha256 does not match the active SKILL.md.",
            "The map is stale for this recorder invocation.",
            "Reconcile and explicitly accept a map with the active skill before appending.",
        )
    elements: dict[tuple[str, str], dict[str, Any]] = {}
    for component in value.get("components", []):
        if not isinstance(component, dict):
            continue
        component_id = component.get("component_id")
        for element in component.get("elements", []):
            if isinstance(element, dict) and isinstance(component_id, str) and isinstance(element.get("element_id"), str):
                elements[(component_id, element["element_id"])] = element
    if not elements:
        _raise(
            "MAP_NOT_ACCEPTED",
            "The accepted map contains no addressable elements.",
            "Claims require component and element references.",
            "No v2 claim can be validated.",
            "Accept a non-empty component map.",
        )
    return {
        "value": value,
        "path": map_path,
        "relative_path": relative_map,
        "sha256": _sha256_file(map_path),
        "elements": elements,
    }


def _normalize_input(raw: Any, map_info: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        _raise(
            "RECORD_SCHEMA_UNSUPPORTED",
            "The v2 record input must be a JSON object.",
            "The top-level value has the wrong type.",
            "The record cannot be validated.",
            "Use the v2 template object.",
        )
    _reject_unknown(
        raw,
        {
            "schema_version",
            "objective",
            "scope",
            "authority",
            "evidence_items",
            "claims",
            "bindings",
            "limitations",
            "summary",
            "unresolved_uncertainties",
        },
        "record",
    )
    if raw.get("schema_version") != SCHEMA_VERSION:
        _raise(
            "RECORD_SCHEMA_UNSUPPORTED",
            f"This command requires schema_version {SCHEMA_VERSION}.",
            f"Observed schema_version: {raw.get('schema_version')!r}.",
            "The record cannot be processed as v2.",
            "Use the v2 template or the legacy flag-only command for v1.",
        )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "objective": _text(raw.get("objective"), "objective"),
        "scope": _text_list(raw.get("scope"), "scope", nonempty=True),
        "authority": _text_list(raw.get("authority"), "authority", nonempty=True),
    }

    raw_evidence = raw.get("evidence_items")
    if not isinstance(raw_evidence, list) or len(raw_evidence) > MAX_EVIDENCE:
        _raise(
            "RECORD_SCHEMA_UNSUPPORTED",
            f"evidence_items must be an array with at most {MAX_EVIDENCE} items.",
            "The evidence registry is missing, invalid, or oversized.",
            "The record cannot be validated.",
            "Provide a bounded evidence_items array.",
        )
    evidence_items: list[dict[str, Any]] = []
    evidence_ids: set[str] = set()
    for index, item in enumerate(raw_evidence):
        field = f"evidence_items[{index}]"
        if not isinstance(item, dict):
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"{field} must be an object.", "Wrong item type.", "The record cannot be validated.", "Use an evidence item object.")
        _reject_unknown(item, {"evidence_id", "source", "locator", "method", "observed_summary"}, field)
        evidence_id = _identifier(item.get("evidence_id"), f"{field}.evidence_id")
        if evidence_id in evidence_ids:
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"Duplicate evidence_id: {evidence_id}.", "Evidence IDs must be unique.", "Bindings would be ambiguous.", "Rename or deduplicate the evidence item.")
        evidence_ids.add(evidence_id)
        method = _text(item.get("method"), f"{field}.method", maximum=40)
        if method not in METHODS:
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"Unsupported evidence method: {method}.", "The method is outside the v2 vocabulary.", "The evidence item cannot be validated.", "Choose a documented evidence method.")
        source = _normalize_source(item.get("source"), f"{field}.source")
        locator = _normalize_locator(item.get("locator"), f"{field}.locator")
        if method == "executed_test" and _looks_like_test_source(source):
            _raise(
                "EXECUTED_TEST_RECEIPT_REQUIRED",
                f"{field} labels test source code as executed evidence.",
                "Reading a test definition does not establish that the test ran.",
                "The evidence item cannot support an executed-test claim.",
                "Point to a persisted test result, log, or verification receipt; use inspected/context for source code.",
            )
        evidence_items.append(
            {
                "evidence_id": evidence_id,
                "source": source,
                "locator": locator,
                "method": method,
                "observed_summary": _safe_observation(item.get("observed_summary"), f"{field}.observed_summary"),
            }
        )
    result["evidence_items"] = evidence_items

    raw_claims = raw.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims or len(raw_claims) > MAX_CLAIMS:
        _raise("RECORD_SCHEMA_UNSUPPORTED", f"claims must contain 1-{MAX_CLAIMS} items.", "The claim registry is empty, invalid, or oversized.", "The record cannot be validated.", "Provide at least one bounded claim.")
    claims: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    for index, claim in enumerate(raw_claims):
        field = f"claims[{index}]"
        if not isinstance(claim, dict):
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"{field} must be an object.", "Wrong item type.", "The record cannot be validated.", "Use a claim object.")
        _reject_unknown(claim, {"claim_id", "statement", "element_ref", "material", "status", "rationale"}, field)
        claim_id = _identifier(claim.get("claim_id"), f"{field}.claim_id")
        if claim_id in claim_ids:
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"Duplicate claim_id: {claim_id}.", "Claim IDs must be unique.", "Summary and binding references would be ambiguous.", "Rename or deduplicate the claim.")
        claim_ids.add(claim_id)
        element_ref = claim.get("element_ref")
        if not isinstance(element_ref, dict):
            _raise("CLAIM_ELEMENT_UNKNOWN", f"{field}.element_ref must be an object.", "The claim has no structural reference.", "The claim cannot be validated.", "Reference an accepted component and element ID.")
        _reject_unknown(element_ref, {"component_id", "element_id"}, f"{field}.element_ref")
        component_id = _identifier(element_ref.get("component_id"), f"{field}.element_ref.component_id")
        element_id = _identifier(element_ref.get("element_id"), f"{field}.element_ref.element_id")
        if (component_id, element_id) not in map_info["elements"]:
            _raise("CLAIM_ELEMENT_UNKNOWN", f"Claim {claim_id!r} references unknown element {component_id}/{element_id}.", "The pair is absent from the bound accepted map.", "The claim cannot be appended.", "Choose an element printed by preflight or explicitly accept a new map.")
        material = claim.get("material")
        if not isinstance(material, bool):
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"{field}.material must be boolean.", "Materiality has the wrong type.", "The claim cannot be validated.", "Use true or false.")
        status_value = _text(claim.get("status"), f"{field}.status", maximum=40)
        if status_value not in CLAIM_STATUSES:
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"Unsupported claim status: {status_value}.", "The status is outside the v2 vocabulary.", "The claim cannot be validated.", "Choose a documented claim status.")
        statement = _text(claim.get("statement"), f"{field}.statement")
        claims.append(
            {
                "claim_id": claim_id,
                "statement": statement,
                "claim_digest": _sha256_bytes(_canonical_bytes(statement)),
                "element_ref": {"component_id": component_id, "element_id": element_id},
                "material": material,
                "status": status_value,
                "rationale": _text(claim.get("rationale"), f"{field}.rationale"),
            }
        )
    result["claims"] = claims

    raw_bindings = raw.get("bindings")
    if not isinstance(raw_bindings, list) or len(raw_bindings) > MAX_BINDINGS:
        _raise("RECORD_SCHEMA_UNSUPPORTED", f"bindings must be an array with at most {MAX_BINDINGS} items.", "The binding registry is invalid or oversized.", "The record cannot be validated.", "Provide a bounded bindings array.")
    bindings: list[dict[str, str]] = []
    binding_keys: set[tuple[str, str, str]] = set()
    for index, binding in enumerate(raw_bindings):
        field = f"bindings[{index}]"
        if not isinstance(binding, dict):
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"{field} must be an object.", "Wrong item type.", "The record cannot be validated.", "Use a binding object.")
        _reject_unknown(binding, {"claim_id", "evidence_id", "role"}, field)
        claim_id = _identifier(binding.get("claim_id"), f"{field}.claim_id")
        evidence_id = _identifier(binding.get("evidence_id"), f"{field}.evidence_id")
        role = _text(binding.get("role"), f"{field}.role", maximum=40)
        if claim_id not in claim_ids or evidence_id not in evidence_ids or role not in ROLES:
            _raise("RECORD_REFERENCE_INVALID", f"{field} has a dangling reference or unsupported role.", "Every binding must resolve to one claim, one evidence item, and one defined role.", "The record cannot be validated.", "Correct the IDs and choose supports, contradicts, limits, or context.")
        key = (claim_id, evidence_id, role)
        if key in binding_keys:
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"Duplicate binding: {claim_id}/{evidence_id}/{role}.", "Bindings must be unique.", "The record cannot be validated.", "Remove the duplicate binding.")
        binding_keys.add(key)
        bindings.append({"claim_id": claim_id, "evidence_id": evidence_id, "role": role})
    result["bindings"] = bindings

    raw_limitations = raw.get("limitations")
    if not isinstance(raw_limitations, list) or len(raw_limitations) > MAX_CLAIMS:
        _raise("RECORD_SCHEMA_UNSUPPORTED", "limitations must be a bounded array.", "The limitation registry is invalid or oversized.", "The record cannot be validated.", "Provide a bounded limitations array.")
    limitations: list[dict[str, Any]] = []
    limitation_ids: set[str] = set()
    for index, limitation in enumerate(raw_limitations):
        field = f"limitations[{index}]"
        if not isinstance(limitation, dict):
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"{field} must be an object.", "Wrong item type.", "The record cannot be validated.", "Use a limitation object.")
        _reject_unknown(limitation, {"limitation_id", "text", "claim_ids", "evidence_ids"}, field)
        limitation_id = _identifier(limitation.get("limitation_id"), f"{field}.limitation_id")
        if limitation_id in limitation_ids:
            _raise("RECORD_SCHEMA_UNSUPPORTED", f"Duplicate limitation_id: {limitation_id}.", "Limitation IDs must be unique.", "Boundary references would be ambiguous.", "Rename or deduplicate the limitation.")
        limitation_ids.add(limitation_id)
        limitation_claim_ids = [_identifier(item, f"{field}.claim_ids") for item in _text_list(limitation.get("claim_ids"), f"{field}.claim_ids", nonempty=True)]
        limitation_evidence_ids = [_identifier(item, f"{field}.evidence_ids") for item in _text_list(limitation.get("evidence_ids"), f"{field}.evidence_ids")]
        if not set(limitation_claim_ids) <= claim_ids or not set(limitation_evidence_ids) <= evidence_ids:
            _raise("RECORD_REFERENCE_INVALID", f"{field} contains dangling claim or evidence IDs.", "Every limitation reference must resolve.", "The record cannot be validated.", "Correct the referenced IDs.")
        limitations.append({"limitation_id": limitation_id, "text": _text(limitation.get("text"), f"{field}.text"), "claim_ids": limitation_claim_ids, "evidence_ids": limitation_evidence_ids})
    result["limitations"] = limitations

    summary = raw.get("summary")
    if not isinstance(summary, dict):
        _raise("RECORD_SCHEMA_UNSUPPORTED", "summary must be an object.", "The v2 summary is missing.", "The strongest-claim boundary cannot be validated.", "Use the v2 summary shape.")
    _reject_unknown(summary, {"strongest_safe_claim_id", "claim_boundary_ids", "no_supported_claim"}, "summary")
    no_supported = summary.get("no_supported_claim")
    if not isinstance(no_supported, bool):
        _raise("RECORD_SCHEMA_UNSUPPORTED", "summary.no_supported_claim must be boolean.", "The explicit sentinel has the wrong type.", "The summary cannot be validated.", "Use true or false.")
    strongest_raw = summary.get("strongest_safe_claim_id")
    strongest = None if strongest_raw is None else _identifier(strongest_raw, "summary.strongest_safe_claim_id")
    boundary_ids = [_identifier(item, "summary.claim_boundary_ids") for item in _text_list(summary.get("claim_boundary_ids"), "summary.claim_boundary_ids")]
    if not set(boundary_ids) <= limitation_ids:
        _raise("RECORD_REFERENCE_INVALID", "summary.claim_boundary_ids contains an unknown limitation.", "The summary boundary does not resolve.", "The record cannot be validated.", "Reference declared limitation IDs only.")
    if no_supported and strongest is not None:
        _raise("STRONGEST_CLAIM_UNBOUND", "A no-supported-claim summary cannot also name a strongest claim.", "The summary sentinel and claim reference conflict.", "The record cannot be validated.", "Set strongest_safe_claim_id to null or no_supported_claim to false.")
    if not no_supported and (strongest is None or strongest not in claim_ids):
        _raise("STRONGEST_CLAIM_UNBOUND", "The summary does not resolve to a declared strongest safe claim.", "no_supported_claim is false but the strongest claim ID is null or unknown.", "The record cannot be validated.", "Reference one eligible declared claim.")
    result["summary"] = {"strongest_safe_claim_id": strongest, "claim_boundary_ids": boundary_ids, "no_supported_claim": no_supported}
    result["unresolved_uncertainties"] = _text_list(raw.get("unresolved_uncertainties"), "unresolved_uncertainties")
    _validate_binding_invariants(result)
    return result


def _validate_binding_invariants(value: dict[str, Any], freshness: dict[str, str] | None = None) -> None:
    by_claim: dict[str, list[dict[str, str]]] = {claim["claim_id"]: [] for claim in value["claims"]}
    for binding in value["bindings"]:
        by_claim[binding["claim_id"]].append(binding)
    limitations_by_claim: dict[str, set[str]] = {claim_id: set() for claim_id in by_claim}
    declared_limit_pairs: set[tuple[str, str]] = set()
    for limitation in value["limitations"]:
        for claim_id in limitation["claim_ids"]:
            limitations_by_claim[claim_id].add(limitation["limitation_id"])
            for evidence_id in limitation["evidence_ids"]:
                declared_limit_pairs.add((claim_id, evidence_id))
    bound_limit_pairs = {
        (binding["claim_id"], binding["evidence_id"])
        for binding in value["bindings"]
        if binding["role"] == "limits"
    }
    if declared_limit_pairs != bound_limit_pairs:
        _raise(
            "BINDING_MISSING",
            "Limitation evidence references and limits bindings do not match exactly.",
            "Every evidence-backed limitation needs one explicit limits edge, and every limits edge needs a named limitation.",
            "The record cannot expose a reliable limitation graph.",
            "Add or remove limitation evidence references and limits bindings so the pairs match.",
        )
    strongest = value["summary"]["strongest_safe_claim_id"]
    for claim in value["claims"]:
        claim_id = claim["claim_id"]
        bindings = by_claim[claim_id]
        support = [item for item in bindings if item["role"] == "supports"]
        contradictions = [item for item in bindings if item["role"] == "contradicts"]
        if claim["status"] in {"supported", "partially_supported"} and not support:
            _raise("BINDING_MISSING", f"Claim {claim_id!r} is {claim['status']} but has no supporting evidence binding.", "A status assertion exists without structural support.", "The claim cannot be appended or selected as strongest.", "Add a supports binding or lower the claim status.")
        if claim["status"] == "contradicted" and not contradictions:
            _raise("BINDING_MISSING", f"Contradicted claim {claim_id!r} has no contradicting evidence binding.", "Counterevidence is not identified.", "The claim boundary cannot be audited.", "Add a contradicts binding or change the status.")
        if claim["status"] == "partially_supported" and not limitations_by_claim[claim_id]:
            _raise("BINDING_MISSING", f"Partially supported claim {claim_id!r} has no explicit limitation.", "Partial support requires a named boundary.", "The claim cannot be appended.", "Add a limitation that references the claim.")
        if claim["status"] in {"untested", "invalidly_specified", "not_applicable"} and (support or contradictions):
            _raise("CLAIM_STATUS_CONFLICT", f"Claim {claim_id!r} is {claim['status']} but has support or contradiction bindings.", "The declared status conflicts with its evidence roles.", "The record cannot be validated.", "Update the status or keep only context/limitation bindings.")
        if contradictions and claim["status"] == "supported":
            code = "STRONGEST_CLAIM_UNBOUND" if claim_id == strongest else "CLAIM_STATUS_CONFLICT"
            _raise(code, f"Supported claim {claim_id!r} has unresolved contradicting evidence.", "A supported status cannot coexist with unresolved counterevidence.", "The claim is not eligible as a safe supported claim.", "Use partially_supported or contradicted and state the boundary.")
        if freshness is not None and claim["status"] in {"supported", "partially_supported"}:
            if not any(freshness[item["evidence_id"]] in CURRENT_FRESHNESS for item in support):
                _raise("EVIDENCE_DIGEST_MISMATCH", f"Claim {claim_id!r} has no current supporting evidence.", "All supporting bindings are stale, missing, or unverifiable.", "The claim cannot be appended as supported.", "Refresh or immutably identify supporting evidence.")
    if value["summary"]["no_supported_claim"] and any(
        claim["status"] in {"supported", "partially_supported"} for claim in value["claims"]
    ):
        _raise(
            "STRONGEST_CLAIM_UNBOUND",
            "The no-supported-claim sentinel conflicts with an eligible supported status.",
            "A supported or partially supported claim exists while the summary says none exists.",
            "The summary understates or inconsistently represents the record.",
            "Select the strongest eligible material claim or lower the unsupported claim status.",
        )
    if strongest is not None:
        claim = next(item for item in value["claims"] if item["claim_id"] == strongest)
        if not claim["material"]:
            _raise("STRONGEST_CLAIM_UNBOUND", f"Claim {strongest!r} is non-material and cannot be selected as strongest.", "The strongest-safe summary is reserved for material claims.", "The summary is invalid.", "Select an eligible material claim or use the no-supported sentinel.")
        if claim["status"] not in {"supported", "partially_supported"}:
            _raise("STRONGEST_CLAIM_UNBOUND", f"Claim {strongest!r} is not eligible to be strongest.", f"Its status is {claim['status']}.", "The summary overstates the claim.", "Choose a supported or partially supported claim, or use the no-supported sentinel.")
        required_boundaries = limitations_by_claim[strongest]
        if required_boundaries != set(value["summary"]["claim_boundary_ids"]):
            _raise("STRONGEST_CLAIM_UNBOUND", f"The strongest claim {strongest!r} does not exactly match its declared limitations.", "Its claim-boundary IDs do not include every applicable limitation.", "The rendered strongest claim would hide a boundary.", "Add every applicable limitation ID to summary.claim_boundary_ids.")
        if freshness is not None:
            for binding in by_claim[strongest]:
                if binding["role"] != "context" and freshness[binding["evidence_id"]] not in CURRENT_FRESHNESS:
                    _raise("STRONGEST_CLAIM_UNBOUND", f"The strongest claim {strongest!r} depends on non-current evidence {binding['evidence_id']!r}.", f"Freshness is {freshness[binding['evidence_id']]!r}.", "The strongest claim binding is incomplete.", "Refresh local evidence or supply an immutable external identity.")


def _materialize_evidence(item: dict[str, Any], project_root: Path, cache: dict[str, tuple[Path, bytes]]) -> dict[str, Any]:
    source = item["source"]
    if source["kind"] == "https":
        freshness = "declared_immutable" if source.get("revision") or source.get("sha256") else "unverifiable"
        selection_sha = source.get("sha256")
        identity = {"source": source, "locator": item["locator"], "method": item["method"], "selection_sha256": selection_sha}
        return {**item, "source": source, "selection_sha256": selection_sha, "freshness": freshness, "identity_sha256": _sha256_bytes(_canonical_bytes(identity))}
    relative = source["path"]
    if relative not in cache:
        path = _safe_file(project_root, relative)
        cache[relative] = (path, _read_stable(path))
    path, data = cache[relative]
    selected = _select_bytes(data, item["locator"], relative)
    source_value = {
        "kind": "file",
        "path": relative,
        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "byte_size": len(data),
        "sha256": _sha256_bytes(data),
    }
    selection_sha = _sha256_bytes(selected)
    identity = {"source": source_value, "locator": item["locator"], "method": item["method"], "selection_sha256": selection_sha}
    return {**item, "source": source_value, "selection_sha256": selection_sha, "freshness": "current", "identity_sha256": _sha256_bytes(_canonical_bytes(identity))}


def _scan_status(claims: list[dict[str, Any]]) -> str:
    statuses = [claim["status"] for claim in claims if claim["material"]]
    if any(status in {"contradicted", "invalidly_specified"} for status in statuses):
        return "FAIL"
    if any(status in {"partially_supported", "untested"} for status in statuses):
        return "PARTIAL"
    if statuses and all(status == "not_applicable" for status in statuses):
        return "NA"
    return "PASS"


def _contract_identities(skill_root: Path) -> dict[str, str]:
    schema_path = skill_root / "references" / "scan-record-output-v2.schema.json"
    return {
        "output_schema_sha256": _sha256_file(schema_path),
        "renderer_id": RENDERER_ID,
        "renderer_sha256": _sha256_bytes(RENDERER_ID.encode("utf-8")),
    }


def _build_record(normalized: dict[str, Any], map_info: dict[str, Any], skill_root: Path, project_root: Path) -> dict[str, Any]:
    engine = verified_engine_summary(skill_root)
    cache: dict[str, tuple[Path, bytes]] = {}
    evidence = [_materialize_evidence(item, project_root, cache) for item in normalized["evidence_items"]]
    freshness = {item["evidence_id"]: item["freshness"] for item in evidence}
    _validate_binding_invariants(normalized, freshness)
    now = datetime.now(timezone.utc)
    scan_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}"
    claims = copy.deepcopy(normalized["claims"])
    strongest_id = normalized["summary"]["strongest_safe_claim_id"]
    strongest_text = None
    if strongest_id is not None:
        strongest_text = next(claim["statement"] for claim in claims if claim["claim_id"] == strongest_id)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "record_kind": RECORD_KIND,
        "scan": {
            "scan_id": scan_id,
            "recorded_at_utc": now.isoformat().replace("+00:00", "Z"),
            "recorder_version": RECORDER_VERSION,
            "skill_name": "analyze-project-claims",
            "skill_sha256": _sha256_file(skill_root / "SKILL.md"),
            "engine_identity": engine,
            "accepted_map": {
                "map_id": map_info["value"]["map_id"],
                "path": map_info["relative_path"],
                "sha256": map_info["sha256"],
            },
            "objective": normalized["objective"],
            "scope": normalized["scope"],
            "authority": normalized["authority"],
        },
        "evidence_items": evidence,
        "claims": claims,
        "bindings": copy.deepcopy(normalized["bindings"]),
        "limitations": copy.deepcopy(normalized["limitations"]),
        "summary": {
            "scan_status": _scan_status(claims),
            "claim_count": len(claims),
            "material_claim_count": sum(1 for claim in claims if claim["material"]),
            "claim_counts": dict(sorted(Counter(claim["status"] for claim in claims).items())),
            "evidence_count": len(evidence),
            "strongest_safe_claim_id": strongest_id,
            "strongest_safe_claim": strongest_text,
            "claim_boundary_ids": normalized["summary"]["claim_boundary_ids"],
            "no_supported_claim": normalized["summary"]["no_supported_claim"],
            "unresolved_uncertainties": normalized["unresolved_uncertainties"],
        },
    }
    result["integrity"] = _contract_identities(skill_root)
    result["integrity"]["canonical_payload_sha256"] = _sha256_bytes(_canonical_bytes(result))
    return result


def _verify_record_integrity(record: dict[str, Any]) -> None:
    integrity = record.get("integrity")
    expected = integrity.get("canonical_payload_sha256") if isinstance(integrity, dict) else None
    payload = copy.deepcopy(record)
    payload_integrity = payload.get("integrity")
    if isinstance(payload_integrity, dict):
        payload_integrity.pop("canonical_payload_sha256", None)
    if not isinstance(expected, str) or _sha256_bytes(_canonical_bytes(payload)) != expected:
        _raise("RECORD_INTEGRITY_MISMATCH", "The persisted record fails its canonical integrity check.", "The payload no longer matches its stored digest.", "The record must not be trusted or rendered as current.", "Restore the original record or append a new validated record.")


def _atomic_create(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _raise("RECORD_COMMIT_FAILED", f"Refusing to overwrite existing file {path}.", "Append-only targets must be unique.", "No existing record was changed.", "Choose a new output path or retry to generate a new scan ID.")
    handle = tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False)
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
        except OSError as exc:
            if path.exists():
                raise FileExistsError(path) from exc
            raise OSError(
                "The filesystem cannot perform a no-replace atomic link for the append-only target."
            ) from exc
        else:
            temp_path.unlink()
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _atomic_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False)
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _markdown_text(value: Any) -> str:
    text = re.sub(r"[\r\n\t]+", " ", str(value)).strip()
    text = "".join(char for char in text if unicodedata.category(char) not in {"Cc", "Cf", "Cs"})
    for token in ("\\", "`", "*", "_", "{", "}", "[", "]", "(", ")", "<", ">", "#", "!", "|"):
        text = text.replace(token, "\\" + token)
    return text


def _locator_label(locator: dict[str, Any]) -> str:
    if locator["kind"] == "whole_file":
        return "whole file"
    if locator["kind"] == "line_range":
        return f"lines {locator['start']}-{locator['end']}"
    return f"{locator['kind']}: {locator['value']}"


def _legacy_render(record: dict[str, Any]) -> str:
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    claim = summary.get("strongest_safe_claim", "Unknown legacy claim")
    return "\n".join(
        [
            "# Legacy scan record",
            "",
            "> **LEGACY_RECORD_UNBOUND**: this v1 record is readable but has no exact claim-to-evidence binding.",
            "> No evidence hashes, support relationships, or semantic status were invented during rendering.",
            "",
            "## Historical strongest-safe-claim prose",
            "",
            _markdown_text(claim),
            "",
            "## Verification boundary",
            "",
            "Recreate and human-review this audit as v2 before treating the claim as evidence-bound.",
            "",
        ]
    )


def _required_repair(status_value: str) -> str:
    return {
        "supported": "No repair declared; reverify when evidence or authority changes.",
        "partially_supported": "Resolve the named limitations or preserve the bounded status.",
        "contradicted": "Resolve the counterevidence before asserting this claim.",
        "untested": "Collect current evidence and add an explicit binding.",
        "invalidly_specified": "Rewrite the claim so it can be tested before binding evidence.",
        "not_applicable": "No repair; preserve the applicability rationale.",
    }[status_value]


def render_record(record: dict[str, Any]) -> str:
    if record.get("schema_version") != SCHEMA_VERSION or record.get("record_kind") != RECORD_KIND:
        return _legacy_render(record)
    _verify_record_integrity(record)
    lines = [
        "# Evidence-bound audit record",
        "",
        "> Derived, non-authoritative view. The persisted JSON record is the authority.",
        "> Artifact verification establishes identity and freshness, not semantic entailment.",
        "",
        f"- Record: `{_markdown_text(record['scan']['scan_id'])}`",
        f"- Record digest: `{record['integrity']['canonical_payload_sha256']}`",
        f"- Output schema: `{record['integrity']['output_schema_sha256']}`",
        f"- Renderer: `{_markdown_text(record['integrity']['renderer_id'])}` (`{record['integrity']['renderer_sha256']}`)",
        f"- Accepted map: `{_markdown_text(record['scan']['accepted_map']['map_id'])}` (`{record['scan']['accepted_map']['sha256']}`)",
        f"- Scan status: **{_markdown_text(record['summary']['scan_status'])}**",
        "",
        "## Strongest safe claim",
        "",
    ]
    if record["summary"]["no_supported_claim"]:
        lines.append("No supported material claim was selected.")
    else:
        lines.extend(
            [
                f"`{_markdown_text(record['summary']['strongest_safe_claim_id'])}`",
                "",
                _markdown_text(record["summary"]["strongest_safe_claim"]),
            ]
        )
    evidence_by_id = {item["evidence_id"]: item for item in record["evidence_items"]}
    bindings_by_claim: dict[str, list[dict[str, str]]] = {claim["claim_id"]: [] for claim in record["claims"]}
    for binding in record["bindings"]:
        bindings_by_claim[binding["claim_id"]].append(binding)
    lines.extend(["", "## Claims", ""])
    for claim in record["claims"]:
        ref = claim["element_ref"]
        lines.extend(
            [
                f"### `{_markdown_text(claim['claim_id'])}` — {_markdown_text(claim['status'])}",
                "",
                _markdown_text(claim["statement"]),
                "",
                f"- Structural element: `{_markdown_text(ref['component_id'])}/{_markdown_text(ref['element_id'])}`",
                f"- Material: `{str(claim['material']).lower()}`",
                f"- Human rationale: {_markdown_text(claim['rationale'])}",
                f"- Required repair: {_markdown_text(_required_repair(claim['status']))}",
            ]
        )
        bindings = sorted(bindings_by_claim[claim["claim_id"]], key=lambda item: (item["role"], item["evidence_id"]))
        if not bindings:
            lines.append("- Evidence bindings: none")
        for binding in bindings:
            evidence = evidence_by_id[binding["evidence_id"]]
            source = evidence["source"]
            if source["kind"] == "file":
                destination = quote(source["path"], safe="/")
                source_label = f"[{_markdown_text(source['path'])}](<{destination}>)"
            else:
                destination = quote(source["url"], safe=":/@-._~!$&'()*+,;=%")
                source_label = f"[{_markdown_text(source['url'])}](<{destination}>)"
            lines.append(
                f"- **{binding['role']}** `{_markdown_text(evidence['evidence_id'])}`: {source_label}; "
                f"{_markdown_text(_locator_label(evidence['locator']))}; freshness `{evidence['freshness']}`; "
                f"artifact `{source.get('sha256', 'unavailable')}`; selection `{evidence.get('selection_sha256') or 'unavailable'}`"
            )
            lines.append(f"  - Observation: {_markdown_text(evidence['observed_summary'])}")
    lines.extend(["", "## Limitations", ""])
    if record["limitations"]:
        for limitation in record["limitations"]:
            lines.append(f"- `{_markdown_text(limitation['limitation_id'])}`: {_markdown_text(limitation['text'])}")
    else:
        lines.append("- None declared.")
    lines.extend(["", "## Unresolved uncertainties", ""])
    uncertainties = record["summary"]["unresolved_uncertainties"]
    lines.extend([f"- {_markdown_text(item)}" for item in uncertainties] or ["- None declared."])
    lines.extend(
        [
            "",
            "## Verification boundary",
            "",
            "**Semantic review required.** Verified bindings show which exact evidence was associated with a claim. They do not establish that the evidence is sufficient, independent, or logically entails the claim.",
            "",
        ]
    )
    output = "\n".join(lines)
    if len(output.encode("utf-8")) > MAX_RENDER_BYTES:
        _raise("REPORT_TOO_LARGE", "The deterministic report exceeds its size limit.", "The record contains too much renderable text.", "No report was written.", "Reduce bounded summaries or split the audit.")
    return output


def _parse_locator_argument(value: str) -> dict[str, Any]:
    if value == "whole-file":
        return {"kind": "whole_file"}
    if value.startswith("json-pointer:"):
        return {"kind": "json_pointer", "value": value[len("json-pointer:") :]}
    if value.startswith("artifact-key:"):
        return {"kind": "artifact_key", "value": value[len("artifact-key:") :]}
    if value.startswith("test-case:"):
        return {"kind": "test_case", "value": value[len("test-case:") :]}
    if value.startswith("line-range:"):
        match = re.fullmatch(r"line-range:(\d+)-(\d+)", value)
        if match:
            return {"kind": "line_range", "start": int(match.group(1)), "end": int(match.group(2))}
    _raise("EVIDENCE_LOCATOR_UNSUPPORTED", f"Locator argument {value!r} is unsupported.", "The helper expects whole-file or a documented KIND:VALUE form.", "No evidence identity was computed.", "Use json-pointer:/path, line-range:1-3, test-case:name, or artifact-key:key.")


def _write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    _atomic_create(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def _preflight(args: argparse.Namespace, skill_root: Path) -> int:
    map_info = _load_map(args.map_root, args.project_root, skill_root)
    engine = verified_engine_summary(skill_root)
    eligible = [f"{component}/{element}" for component, element in sorted(map_info["elements"])]
    print(json.dumps({"status": "ready", "accepted_map": {"map_id": map_info["value"]["map_id"], "sha256": map_info["sha256"], "path": map_info["relative_path"]}, "engine_identity": engine, "eligible_elements": eligible}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _init(args: argparse.Namespace, skill_root: Path) -> int:
    map_info = _load_map(args.map_root, args.project_root, skill_root)
    component_id, element_id = sorted(map_info["elements"])[0]
    value = {
        "schema_version": SCHEMA_VERSION,
        "objective": "State the audit question and success condition.",
        "scope": ["path/or/artifact/in/scope"],
        "authority": ["authoritative/source/path"],
        "evidence_items": [],
        "claims": [{"claim_id": "claim-to-review", "statement": "Replace with one material claim.", "element_ref": {"component_id": component_id, "element_id": element_id}, "material": True, "status": "untested", "rationale": "Human semantic review has not yet bound evidence."}],
        "bindings": [],
        "limitations": [],
        "summary": {"strongest_safe_claim_id": None, "claim_boundary_ids": [], "no_supported_claim": True},
        "unresolved_uncertainties": ["Evidence bindings have not yet been authored."],
    }
    _write_json_exclusive(args.output, value)
    print(json.dumps({"status": "draft_created", "output": str(args.output.resolve()), "accepted_map_id": map_info["value"]["map_id"]}, indent=2))
    return 0


def _evidence_digest(args: argparse.Namespace) -> int:
    evidence_id = _identifier(args.id, "evidence_id")
    item = {"evidence_id": evidence_id, "source": {"kind": "file", "path": _relative_posix_path(args.source, "source")}, "locator": _normalize_locator(_parse_locator_argument(args.locator), "locator"), "method": args.method, "observed_summary": args.observed_summary}
    item["method"] = _text(item["method"], "method", maximum=40)
    if item["method"] not in METHODS:
        _raise("RECORD_SCHEMA_UNSUPPORTED", f"Unsupported evidence method: {item['method']}.", "The method is outside the v2 vocabulary.", "No evidence identity was computed.", "Choose a documented method.")
    item["observed_summary"] = _safe_observation(item["observed_summary"], "observed_summary")
    if item["method"] == "executed_test" and _looks_like_test_source(item["source"]):
        _raise(
            "EXECUTED_TEST_RECEIPT_REQUIRED",
            "The evidence helper was given test source code as executed evidence.",
            "Reading a test definition does not establish that the test ran.",
            "No execution-evidence identity was emitted.",
            "Point to a persisted test result, log, or verification receipt.",
        )
    materialized = _materialize_evidence(item, args.project_root, {})
    print(json.dumps({"evidence_item": item, "computed_identity": {"source_sha256": materialized["source"]["sha256"], "selection_sha256": materialized["selection_sha256"], "identity_sha256": materialized["identity_sha256"]}}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _validate(args: argparse.Namespace, skill_root: Path) -> int:
    map_info = _load_map(args.map_root, args.project_root, skill_root)
    normalized = _normalize_input(_load_json(args.record), map_info)
    print(json.dumps({"status": "valid", "schema_version": SCHEMA_VERSION, "accepted_map_id": map_info["value"]["map_id"], "claim_count": len(normalized["claims"]), "evidence_count": len(normalized["evidence_items"]), "binding_count": len(normalized["bindings"])}, indent=2, sort_keys=True))
    return 0


def _append(args: argparse.Namespace, skill_root: Path) -> int:
    map_info = _load_map(args.map_root, args.project_root, skill_root)
    normalized = _normalize_input(_load_json(args.record), map_info)
    record = _build_record(normalized, map_info, skill_root, args.project_root)
    output = args.log_dir / f"{record['scan']['scan_id']}.json"
    _write_json_exclusive(output, record)
    report_path: Path | None = None
    if args.report_dir is not None:
        report_path = args.report_dir / f"{record['scan']['scan_id']}.md"
        try:
            _atomic_create(report_path, render_record(record).encode("utf-8"))
        except (OSError, AuditRecordError) as exc:
            print(f"REPORT_WRITE_FAILED\n\nProblem: The scan record was committed but its derived report was not written.\nCause: {exc}\nEffect: The JSON record remains authoritative and unchanged.\nFix: Run record_scan.py render --record {output} --output {report_path}\nRetry: record_scan.py render --record {output} --output {report_path}\nDocs: {DOC_URL}#report-write-failed", file=os.sys.stderr)
            return 3
    print(json.dumps({"status": "appended", "log": str(output.resolve()), "report": str(report_path.resolve()) if report_path else None, "scan_id": record["scan"]["scan_id"], "scan_status": record["summary"]["scan_status"], "canonical_payload_sha256": record["integrity"]["canonical_payload_sha256"]}, indent=2, sort_keys=True))
    return 0


def _render(args: argparse.Namespace) -> int:
    value = _load_json(args.record)
    report = render_record(value)
    if args.output is None:
        print(report, end="")
    else:
        _atomic_replace(args.output, report.encode("utf-8"))
        print(json.dumps({"status": "rendered", "record": str(args.record.resolve()), "output": str(args.output.resolve())}, indent=2))
    return 0


def _verify(args: argparse.Namespace, skill_root: Path) -> int:
    record = _load_json(args.record)
    if record.get("schema_version") != SCHEMA_VERSION or record.get("record_kind") != RECORD_KIND:
        output = {"status": "legacy_unbound", "codes": ["LEGACY_RECORD_UNBOUND"], "record": str(args.record.resolve())}
        print(json.dumps(output, indent=2) if args.format == "json" else "LEGACY_RECORD_UNBOUND\nLegacy v1 records are readable but do not carry exact claim-to-evidence bindings.")
        return 3
    _verify_record_integrity(record)
    if (args.map_root is None) != (args.project_root is None) or (
        args.map_root is None and args.project_root is None
    ):
        _raise(
            "VERIFY_CONTEXT_REQUIRED",
            "A v2 verification requires both --map-root and --project-root.",
            "Without the accepted map and project root, current evidence identities cannot be recomputed.",
            "The record was not described as verified.",
            "Provide both roots; use render for a read-only historical view.",
        )
    codes: list[str] = []
    current_contract = _contract_identities(skill_root)
    for field, code in (
        ("output_schema_sha256", "SCHEMA_IDENTITY_MISMATCH"),
        ("renderer_id", "RENDERER_IDENTITY_MISMATCH"),
        ("renderer_sha256", "RENDERER_IDENTITY_MISMATCH"),
    ):
        if record["integrity"].get(field) != current_contract[field]:
            codes.append(code)
    if record["scan"].get("skill_sha256") != _sha256_file(skill_root / "SKILL.md"):
        codes.append("SKILL_IDENTITY_MISMATCH")
    try:
        engine = verified_engine_summary(skill_root)
        if record["scan"].get("engine_identity", {}).get("engine_digest") != engine["engine_digest"]:
            codes.append("ENGINE_IDENTITY_MISMATCH")
    except (EngineIdentityError, OSError):
        codes.append("ENGINE_IDENTITY_MISMATCH")
    if args.map_root is not None and args.project_root is not None:
        try:
            map_info = _load_map(args.map_root, args.project_root, skill_root)
            expected_map = record["scan"].get("accepted_map", {})
            if expected_map.get("map_id") != map_info["value"]["map_id"] or expected_map.get("sha256") != map_info["sha256"]:
                codes.append("MAP_IDENTITY_MISMATCH")
        except AuditRecordError:
            codes.append("MAP_IDENTITY_MISMATCH")
        cache: dict[str, tuple[Path, bytes]] = {}
        for evidence in record["evidence_items"]:
            source = evidence["source"]
            if source.get("kind") != "file":
                if evidence.get("freshness") == "unverifiable":
                    codes.append("EXTERNAL_EVIDENCE_UNVERIFIABLE")
                continue
            relative = source.get("path")
            try:
                if relative not in cache:
                    path = _safe_file(args.project_root, relative)
                    cache[relative] = (path, _read_stable(path))
                _, data = cache[relative]
                selected = _select_bytes(data, evidence["locator"], relative)
                if _sha256_bytes(data) != source.get("sha256") or _sha256_bytes(selected) != evidence.get("selection_sha256"):
                    codes.append("EVIDENCE_DIGEST_MISMATCH")
            except AuditRecordError:
                codes.append("EVIDENCE_DIGEST_MISMATCH")
    if args.report is not None:
        try:
            if args.report.read_text(encoding="utf-8") != render_record(record):
                codes.append("REPORT_OUT_OF_DATE")
        except OSError:
            codes.append("REPORT_OUT_OF_DATE")
    codes = sorted(set(codes))
    output = {"status": "verified" if not codes else "stale", "codes": codes, "record": str(args.record.resolve()), "canonical_payload_sha256": record["integrity"]["canonical_payload_sha256"]}
    if args.format == "json":
        print(json.dumps(output, indent=2, sort_keys=True))
    elif codes:
        print("Verification: STALE\n" + "\n".join(f"- {code}" for code in codes))
    else:
        print("Verification: VERIFIED\nAll local identities and selected evidence digests match.")
    return 0 if not codes else 3


def _draft_v2(args: argparse.Namespace, skill_root: Path) -> int:
    legacy = _load_json(args.legacy_record)
    map_info = _load_map(args.map_root, args.project_root, skill_root)
    component_id, element_id = sorted(map_info["elements"])[0]
    summary = legacy.get("summary") if isinstance(legacy.get("summary"), dict) else {}
    statement = summary.get("strongest_safe_claim") or legacy.get("strongest_safe_claim") or "Legacy strongest-safe-claim prose requires review."
    value = {
        "schema_version": SCHEMA_VERSION,
        "objective": legacy.get("scan", {}).get("objective") or legacy.get("objective") or "Review a legacy scan record as v2.",
        "scope": legacy.get("scan", {}).get("scope") or legacy.get("scope") or ["legacy record"],
        "authority": legacy.get("scan", {}).get("authority") or legacy.get("authority") or ["legacy record"],
        "evidence_items": [],
        "claims": [{"claim_id": "legacy-strongest-safe-claim", "statement": str(statement), "element_ref": {"component_id": component_id, "element_id": element_id}, "material": True, "status": "untested", "rationale": "Copied from legacy prose; no support or semantic status was inferred."}],
        "bindings": [],
        "limitations": [],
        "summary": {"strongest_safe_claim_id": None, "claim_boundary_ids": [], "no_supported_claim": True},
        "unresolved_uncertainties": ["LEGACY_RECORD_UNBOUND: human review and fresh evidence bindings are required."],
    }
    _write_json_exclusive(args.output, value)
    print(json.dumps({"status": "legacy_draft_created", "output": str(args.output.resolve()), "bindings_invented": 0}, indent=2))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and verify evidence-bound scan records.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def map_args(command: argparse.ArgumentParser, *, record: bool = False) -> None:
        if record:
            command.add_argument("--record", required=True, type=Path)
        command.add_argument("--map-root", required=True, type=Path)
        command.add_argument("--project-root", required=True, type=Path)

    preflight = subparsers.add_parser("preflight", help="Verify the engine and accepted map")
    map_args(preflight)
    init = subparsers.add_parser("init", help="Create a safe unbound v2 draft")
    map_args(init)
    init.add_argument("--output", required=True, type=Path)

    evidence = subparsers.add_parser("evidence", help="Evidence authoring helpers")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    digest = evidence_sub.add_parser("digest", help="Compute a local artifact and selection identity")
    digest.add_argument("--source", required=True)
    digest.add_argument("--locator", required=True)
    digest.add_argument("--project-root", required=True, type=Path)
    digest.add_argument("--id", required=True)
    digest.add_argument("--method", default="inspected")
    digest.add_argument("--observed-summary", default="Review the selected evidence before appending.")

    validate = subparsers.add_parser("validate", help="Validate v2 structure and accepted-map references")
    map_args(validate, record=True)
    append = subparsers.add_parser("append", help="Resolve evidence and append a canonical v2 record")
    map_args(append, record=True)
    append.add_argument("--log-dir", required=True, type=Path)
    append.add_argument("--report-dir", type=Path)
    render = subparsers.add_parser("render", help="Render a deterministic Markdown view")
    render.add_argument("--record", required=True, type=Path)
    render.add_argument("--output", type=Path)
    verify = subparsers.add_parser("verify", help="Recompute evidence identity and freshness")
    verify.add_argument("--record", required=True, type=Path)
    verify.add_argument("--map-root", type=Path)
    verify.add_argument("--project-root", type=Path)
    verify.add_argument("--report", type=Path)
    verify.add_argument("--format", choices=("human", "json"), default="human")
    draft = subparsers.add_parser("draft-v2", help="Copy legacy prose into an unbound v2 draft")
    draft.add_argument("--legacy-record", required=True, type=Path)
    map_args(draft)
    draft.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    skill_root = Path(__file__).resolve().parents[2]
    try:
        if args.command == "preflight":
            return _preflight(args, skill_root)
        if args.command == "init":
            return _init(args, skill_root)
        if args.command == "evidence":
            return _evidence_digest(args)
        if args.command == "validate":
            return _validate(args, skill_root)
        if args.command == "append":
            return _append(args, skill_root)
        if args.command == "render":
            return _render(args)
        if args.command == "verify":
            return _verify(args, skill_root)
        return _draft_v2(args, skill_root)
    except (AuditRecordError, EngineIdentityError) as exc:
        print(f"record_scan: {exc}", file=os.sys.stderr)
        return 2
    except OSError as exc:
        print(
            "record_scan: RECORD_IO_ERROR\n\n"
            f"Problem: A filesystem operation failed.\nCause: {exc}\n"
            "Effect: The requested operation did not complete.\n"
            "Fix: Check paths and permissions; append-only history was not intentionally overwritten.\n"
            "Retry: Rerun the same command after correcting the filesystem condition.\n"
            f"Docs: {DOC_URL}#record-io-error",
            file=os.sys.stderr,
        )
        return 2


def dispatch_if_v2(argv: Sequence[str]) -> int | None:
    if argv and (argv[0] in COMMANDS or argv[0] in {"-h", "--help"}):
        return main(argv)
    return None

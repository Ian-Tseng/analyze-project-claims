#!/usr/bin/env python3
"""Consent-gated, native update policy for analyze-project-claims.

This module never downloads or replaces skill files itself. It binds one clean,
tracked user-scope installation and delegates checks/replacement to GitHub CLI.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence
from urllib.parse import urlparse


SCHEMA_VERSION = 1
SKILL_NAME = "analyze-project-claims"
MANIFEST_RELATIVE_PATH = "references/package-manifest.json"
PACKAGE_VERSION_RELATIVE_PATH = "references/package-version.json"
SKILL_NORMALIZATION = "canonical-frontmatter-v1-without-github-metadata"
SUCCESS_LEASE_SECONDS = 24 * 60 * 60
TRANSIENT_BACKOFF_SECONDS = 60 * 60
DEFAULT_TIMEOUT_SECONDS = 20.0
OUTPUT_LIMIT_BYTES = 64 * 1024
MODES = {"unconfigured", "off", "notify", "auto"}
GITHUB_SHA_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
GITHUB_METADATA_PATTERN = re.compile(r"^github-[a-z0-9-]+$")
IGNORED_PARTS = {"__pycache__"}
IGNORED_NAMES = {".DS_Store", "Thumbs.db"}

STATE_KEYS = {
    "schema_version",
    "mode",
    "prompted",
    "installation_id",
    "source_fingerprint",
    "last_attempt_at",
    "last_success_at",
    "next_check_at",
    "suspended",
    "last_outcome",
}


class PolicyError(RuntimeError):
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
    timed_out: bool = False


@dataclass(frozen=True)
class Installation:
    path: Path
    source_url: str
    scope: str
    version: str
    pinned: bool
    tree_sha: str


def default_state() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "unconfigured",
        "prompted": False,
        "installation_id": None,
        "source_fingerprint": None,
        "last_attempt_at": None,
        "last_success_at": None,
        "next_check_at": None,
        "suspended": False,
        "last_outcome": "NEVER",
    }


def _is_nullable_int(value: object) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def validate_state(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != STATE_KEYS:
        raise PolicyError("UPDATE_POLICY_STATE_INVALID", "Update policy state has unknown or missing fields.")
    if value["schema_version"] != SCHEMA_VERSION:
        raise PolicyError("UPDATE_POLICY_STATE_INVALID", "Update policy schema version is unsupported.")
    if value["mode"] not in MODES:
        raise PolicyError("UPDATE_POLICY_STATE_INVALID", "Update policy mode is invalid.")
    if not isinstance(value["prompted"], bool) or not isinstance(value["suspended"], bool):
        raise PolicyError("UPDATE_POLICY_STATE_INVALID", "Update policy booleans are invalid.")
    for key in ("installation_id", "source_fingerprint"):
        item = value[key]
        if item is not None and (not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item)):
            raise PolicyError("UPDATE_POLICY_STATE_INVALID", f"Update policy {key} is invalid.")
    for key in ("last_attempt_at", "last_success_at", "next_check_at"):
        if not _is_nullable_int(value[key]):
            raise PolicyError("UPDATE_POLICY_STATE_INVALID", f"Update policy {key} is invalid.")
    if not isinstance(value["last_outcome"], str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value["last_outcome"]):
        raise PolicyError("UPDATE_POLICY_STATE_INVALID", "Update policy last_outcome is invalid.")
    return dict(value)


def default_state_directory() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / SKILL_NAME if base else Path.home() / "AppData" / "Local" / SKILL_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / SKILL_NAME
    base = os.environ.get("XDG_STATE_HOME")
    return Path(base) / SKILL_NAME if base else Path.home() / ".local" / "state" / SKILL_NAME


class PolicyStore:
    def __init__(self, directory: Path) -> None:
        # Preserve the final path component so _prepare_directory can reject a
        # symlink instead of silently following it through resolve().
        self.directory = directory.expanduser().absolute()
        self.path = self.directory / "update-policy.json"
        self.lock_path = self.directory / "update-policy.lock"

    def _prepare_directory(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise PolicyError("UPDATE_POLICY_STATE_UNSAFE", "Update policy directory cannot be a symbolic link.")
        if os.name != "nt":
            os.chmod(self.directory, 0o700)

    def load(self) -> dict[str, object]:
        if not self.path.exists():
            return default_state()
        if self.path.is_symlink() or not self.path.is_file():
            raise PolicyError("UPDATE_POLICY_STATE_UNSAFE", "Update policy path is not a regular file.")
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PolicyError("UPDATE_POLICY_STATE_INVALID", "Update policy state cannot be read as strict JSON.") from exc
        return validate_state(raw)

    def save(self, state: dict[str, object]) -> None:
        validated = validate_state(state)
        self._prepare_directory()
        payload = (json.dumps(validated, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        fd, temporary_name = tempfile.mkstemp(prefix=".update-policy-", suffix=".tmp", dir=self.directory)
        temporary = Path(temporary_name)
        try:
            if os.name != "nt":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            if os.name != "nt":
                os.chmod(self.path, 0o600)
        except Exception:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise

    @contextlib.contextmanager
    def try_lock(self) -> Iterator[bool]:
        self._prepare_directory()
        handle = self.lock_path.open("a+b")
        acquired = False
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (BlockingIOError, OSError):
                acquired = False
            yield acquired
        finally:
            if acquired:
                with contextlib.suppress(OSError):
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def _bounded_text(handle) -> str:
    handle.seek(0)
    data = handle.read(OUTPUT_LIMIT_BYTES + 1)
    truncated = len(data) > OUTPUT_LIMIT_BYTES
    data = data[:OUTPUT_LIMIT_BYTES]
    text = data.decode("utf-8", errors="replace")
    return text + ("\n[output truncated]" if truncated else "")


class NativeClient:
    def __init__(self, command: Sequence[str] = ("gh",), timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if not command:
            raise ValueError("Native command cannot be empty.")
        self.command = list(command)
        self.timeout = timeout

    def run(self, arguments: Sequence[str]) -> NativeResult:
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                completed = subprocess.run(
                    [*self.command, *arguments],
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    check=False,
                    timeout=self.timeout,
                )
                return NativeResult(
                    completed.returncode,
                    _bounded_text(stdout_file),
                    _bounded_text(stderr_file),
                )
            except FileNotFoundError as exc:
                raise PolicyError(
                    "NATIVE_GH_UNAVAILABLE",
                    "GitHub CLI is unavailable.",
                    "Install a GitHub CLI version that supports `gh skill`.",
                ) from exc
            except subprocess.TimeoutExpired:
                return NativeResult(124, _bounded_text(stdout_file), _bounded_text(stderr_file), timed_out=True)

    def list_installs(self) -> list[dict[str, object]]:
        result = self.run(
            [
                "skill",
                "list",
                "--json",
                "skillName,sourceURL,scope,version,pinned,path",
            ]
        )
        if result.returncode != 0:
            raise PolicyError("NATIVE_LIST_FAILED", "GitHub CLI could not list installed skills.")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PolicyError("NATIVE_LIST_INVALID", "GitHub CLI returned invalid skill-list JSON.") from exc
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise PolicyError("NATIVE_LIST_INVALID", "GitHub CLI skill-list JSON has the wrong shape.")
        return value

    def update(self, *, dry_run: bool) -> NativeResult:
        arguments = ["skill", "update", SKILL_NAME]
        arguments.append("--dry-run" if dry_run else "--all")
        return self.run(arguments)


def normalize_source_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyError("UNTRACKED_INSTALL", "The installed skill has no GitHub source metadata.")
    source = value.strip()
    if source.startswith("git@github.com:"):
        source = "https://github.com/" + source[len("git@github.com:") :]
    elif source.startswith("github.com/"):
        source = "https://" + source
    parsed = urlparse(source)
    try:
        unsupported_port = parsed.port not in {None, 443}
    except ValueError as exc:
        raise PolicyError("UNSUPPORTED_SOURCE", "Automatic upgrades require a canonical GitHub repository URL.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"github.com", "www.github.com"}
        or parsed.username is not None
        or parsed.password is not None
        or unsupported_port
        or parsed.query
        or parsed.fragment
    ):
        raise PolicyError("UNSUPPORTED_SOURCE", "Automatic upgrades require a GitHub.com source.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise PolicyError("UNSUPPORTED_SOURCE", "Automatic upgrades require one GitHub owner/repository source.")
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if (
        not owner
        or not repository
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", owner)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository)
    ):
        raise PolicyError("UNSUPPORTED_SOURCE", "Automatic upgrades require a canonical GitHub repository URL.")
    return f"https://github.com/{owner.lower()}/{repository.lower()}"


def package_version(skill_root: Path) -> str:
    path = skill_root / PACKAGE_VERSION_RELATIVE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError("PACKAGE_VERSION_INVALID", "Package version metadata is missing or invalid JSON.") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "skill_name", "version"}
        or value["schema_version"] != 1
        or value["skill_name"] != SKILL_NAME
        or not isinstance(value["version"], str)
        or not SEMVER_PATTERN.fullmatch(value["version"])
    ):
        raise PolicyError("PACKAGE_VERSION_INVALID", "Package version metadata is invalid.")
    return value["version"]


def source_fingerprint(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def installation_id(source_url: str, skill_root: Path) -> str:
    path = str(skill_root.resolve())
    if os.name == "nt":
        path = path.casefold()
    return hashlib.sha256((source_url + "\0" + path).encode("utf-8")).hexdigest()


def _frontmatter_lines(skill_path: Path) -> list[str]:
    try:
        text = skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "SKILL.md is not readable UTF-8.") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "SKILL.md frontmatter is missing.")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "SKILL.md frontmatter is not closed.") from exc
    return lines[1:end]


def github_metadata(skill_path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    in_metadata = False
    for line in _frontmatter_lines(skill_path):
        if line and not line[0].isspace():
            in_metadata = line.strip() == "metadata:"
            if in_metadata:
                continue
            match = re.match(r"^(github-[a-z0-9-]+):\s*(.+?)\s*$", line)
        elif in_metadata:
            match = re.match(r"^\s+(github-[a-z0-9-]+):\s*(.+?)\s*$", line)
        else:
            match = None
        if match:
            raw = match.group(2).strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
                raw = raw[1:-1]
            metadata[match.group(1)] = raw
    return metadata


def normalized_skill_bytes(skill_path: Path) -> bytes:
    try:
        text = skill_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "SKILL.md is not readable UTF-8.") from exc
    keep_ending = text.endswith("\n")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "SKILL.md frontmatter is missing.")
    try:
        frontmatter_end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "SKILL.md frontmatter is not closed.") from exc

    frontmatter = lines[1:frontmatter_end]
    blocks: list[tuple[str | None, list[str]]] = []
    index = 0
    while index < len(frontmatter):
        line = frontmatter[index]
        if not line.strip():
            index += 1
            continue
        if line[:1].isspace():
            raise PolicyError("PACKAGE_MANIFEST_INVALID", "SKILL.md frontmatter contains an orphaned value.")

        key_match = re.match(r"^([A-Za-z0-9_-]+)\s*:", line)
        key = key_match.group(1) if key_match else None
        block = [line]
        index += 1
        while index < len(frontmatter):
            child = frontmatter[index]
            if child.strip() and not child[:1].isspace():
                break
            block.append(child)
            index += 1

        if key == "metadata":
            filtered: list[str] = []
            for child in block[1:]:
                child_match = re.match(r"^\s+([A-Za-z0-9-]+):", child)
                if child_match and GITHUB_METADATA_PATTERN.fullmatch(child_match.group(1)):
                    continue
                filtered.append(child)
            block = [line, *filtered]
            if not any(item.strip() for item in filtered):
                continue
        elif key and GITHUB_METADATA_PATTERN.fullmatch(key):
            continue
        blocks.append((key, block))

    priority = {"name": 0, "description": 1}
    ordered = sorted(
        enumerate(blocks),
        key=lambda item: (priority.get(item[1][0] or "", 2), item[0]),
    )
    normalized = [line for _, (_, block) in ordered for line in block]
    while normalized and not normalized[-1].strip():
        normalized.pop()

    body = lines[frontmatter_end + 1 :]
    while body and not body[0].strip():
        body.pop(0)
    rebuilt = ["---", *normalized, "---"]
    if body:
        rebuilt.extend(["", *body])
    result = "\n".join(rebuilt)
    if keep_ending:
        result += "\n"
    return result.encode("utf-8")


def _is_link_like(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(reparse_flag and attributes & reparse_flag)


def _reject_package_links(skill_root: Path) -> None:
    root = skill_root.resolve()
    for candidate in root.rglob("*"):
        if _is_link_like(candidate):
            raise PolicyError("PACKAGE_MODIFIED", "Installed package contains a symbolic link or reparse point.")


def _iter_package_files(skill_root: Path) -> Iterator[tuple[str, Path]]:
    root = skill_root.resolve()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST_RELATIVE_PATH:
            continue
        if any(part in IGNORED_PARTS for part in path.relative_to(root).parts):
            continue
        if path.name in IGNORED_NAMES or path.suffix == ".pyc":
            continue
        yield relative, path


def package_file_digest(relative: str, path: Path) -> str:
    data = normalized_skill_bytes(path) if relative == "SKILL.md" else path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def build_package_manifest(skill_root: Path) -> dict[str, object]:
    _reject_package_links(skill_root)
    files = [
        {"path": relative, "sha256": package_file_digest(relative, path)}
        for relative, path in _iter_package_files(skill_root)
    ]
    return {
        "schema_version": 1,
        "skill_name": SKILL_NAME,
        "algorithm": "sha256",
        "skill_normalization": SKILL_NORMALIZATION,
        "files": files,
    }


def verify_package_manifest(skill_root: Path) -> str:
    _reject_package_links(skill_root)
    manifest_path = skill_root / MANIFEST_RELATIVE_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "Package manifest is missing or invalid JSON.") from exc
    expected_keys = {"schema_version", "skill_name", "algorithm", "skill_normalization", "files"}
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "Package manifest has unknown or missing fields.")
    if (
        manifest["schema_version"] != 1
        or manifest["skill_name"] != SKILL_NAME
        or manifest["algorithm"] != "sha256"
        or manifest["skill_normalization"] != SKILL_NORMALIZATION
        or not isinstance(manifest["files"], list)
    ):
        raise PolicyError("PACKAGE_MANIFEST_INVALID", "Package manifest metadata is invalid.")
    actual_files = list(_iter_package_files(skill_root))
    actual_paths = [relative for relative, _ in actual_files]
    entries = manifest["files"]
    manifest_paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise PolicyError("PACKAGE_MANIFEST_INVALID", "Package manifest file entry is invalid.")
        relative = entry["path"]
        digest = entry["sha256"]
        if (
            not isinstance(relative, str)
            or not relative
            or relative.startswith("/")
            or ".." in Path(relative).parts
            or "\\" in relative
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise PolicyError("PACKAGE_MANIFEST_INVALID", "Package manifest path or digest is invalid.")
        manifest_paths.append(relative)
    if manifest_paths != sorted(set(manifest_paths)) or manifest_paths != actual_paths:
        raise PolicyError("PACKAGE_MODIFIED", "Installed package files differ from the release manifest.")
    for entry, (relative, path) in zip(entries, actual_files):
        if entry["sha256"] != package_file_digest(relative, path):
            raise PolicyError("PACKAGE_MODIFIED", f"Installed package file is locally modified: {relative}")
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def write_package_manifest(skill_root: Path) -> Path:
    if github_metadata(skill_root / "SKILL.md"):
        raise PolicyError("MANIFEST_WRITE_REFUSED", "Refusing to regenerate a manifest inside a tracked installation.")
    manifest = build_package_manifest(skill_root)
    path = skill_root / MANIFEST_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return path


def discover_installation(native: NativeClient, skill_root: Path) -> Installation:
    matches = [item for item in native.list_installs() if item.get("skillName") == SKILL_NAME]
    if not matches:
        raise PolicyError(
            "UNTRACKED_INSTALL",
            "This copy is not tracked by GitHub CLI.",
            "Install or adopt it with `gh skill install` before enabling automatic upgrades.",
        )
    if len(matches) != 1:
        raise PolicyError(
            "AMBIGUOUS_INSTALL",
            "More than one installed skill has this name, so an update-by-name is unsafe.",
            "Remove the duplicate or update each installation manually.",
        )
    item = matches[0]
    required = {"path", "sourceURL", "scope", "version", "pinned"}
    if not required.issubset(item):
        raise PolicyError("NATIVE_LIST_INVALID", "GitHub CLI omitted required installation fields.")
    raw_path = item["path"]
    if not isinstance(raw_path, str):
        raise PolicyError("NATIVE_LIST_INVALID", "GitHub CLI returned an invalid installation path.")
    listed_path = Path(raw_path).resolve()
    if listed_path.name == "SKILL.md":
        listed_path = listed_path.parent
    if listed_path != skill_root.resolve():
        raise PolicyError(
            "INSTALL_PATH_MISMATCH",
            "The only tracked installation is not the skill currently running.",
            "Run the update from the tracked copy or reinstall this copy.",
        )
    if not isinstance(item["scope"], str) or not isinstance(item["version"], str) or not isinstance(item["pinned"], bool):
        raise PolicyError("NATIVE_LIST_INVALID", "GitHub CLI returned invalid installation metadata.")
    packaged_version = package_version(skill_root)
    native_version = item["version"][1:] if item["version"].startswith("v") else item["version"]
    if native_version != packaged_version:
        raise PolicyError("VERSION_MISMATCH", "GitHub CLI and package version metadata disagree.")
    source = normalize_source_url(item["sourceURL"])
    metadata = github_metadata(skill_root / "SKILL.md")
    tree_sha = metadata.get("github-tree-sha", "").lower()
    if not GITHUB_SHA_PATTERN.fullmatch(tree_sha):
        raise PolicyError("UNTRACKED_INSTALL", "SKILL.md does not contain a valid GitHub tree SHA.")
    metadata_repo = metadata.get("github-repo")
    if metadata_repo:
        metadata_source = normalize_source_url(
            metadata_repo if metadata_repo.startswith("http") else f"https://github.com/{metadata_repo}"
        )
        if metadata_source != source:
            raise PolicyError("SOURCE_MISMATCH", "GitHub CLI and SKILL.md source metadata disagree.")
    return Installation(listed_path, source, item["scope"], packaged_version, item["pinned"], tree_sha)


def _result(
    status: str,
    state: dict[str, object],
    message: str,
    *,
    action: str | None = None,
    current_version: str | None = None,
    installed_version: str | None = None,
    native_notice: str | None = None,
    emit: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "mode": state["mode"],
        "message": message,
        "action": action,
        "current_version": current_version,
        "installed_version": installed_version,
        "next_check_at": state["next_check_at"],
        "native_notice": native_notice,
        "emit": emit,
    }


class UpdateCoordinator:
    def __init__(
        self,
        skill_root: Path,
        store: PolicyStore,
        native: NativeClient,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.skill_root = skill_root.resolve()
        self.store = store
        self.native = native
        self.now = now

    def _timestamp(self) -> int:
        return max(0, int(self.now()))

    def prompt(self) -> dict[str, object]:
        with self.store.try_lock() as acquired:
            if not acquired:
                state = self.store.load()
                return _result("LOCKED", state, "Another update-policy action is already running.")
            state = self.store.load()
            if state["mode"] != "unconfigured" or state["prompted"]:
                return _result("NO_PROMPT", state, "Update preference is already known or the prompt was already shown.")
            state["prompted"] = True
            state["last_outcome"] = "CONSENT_REQUIRED"
            self.store.save(state)
            return _result(
                "CONSENT_REQUIRED",
                state,
                (
                    "Enable automatic updates for this tracked standalone skill? After a successful check, "
                    "the next automatic check waits at least 24 hours. A transient failure may retry no sooner "
                    "than one hour on a later invocation. The updater never uses --force or --unpin."
                ),
                action="Say `enable automatic updates`, `notify me about updates`, or `disable updates`.",
                emit=True,
            )

    def enable(self, mode: str) -> dict[str, object]:
        if mode not in {"auto", "notify"}:
            raise PolicyError("INVALID_MODE", "Enable mode must be auto or notify.")
        with self.store.try_lock() as acquired:
            if not acquired:
                return _result("LOCKED", self.store.load(), "Another update-policy action is already running.")
            state = self.store.load()
            install = discover_installation(self.native, self.skill_root)
            selected = mode
            degradation: str | None = None
            if mode == "auto":
                try:
                    if install.scope != "user":
                        raise PolicyError("PROJECT_SCOPE", "Project-scope installs are notify-only.")
                    if install.pinned:
                        raise PolicyError("PINNED", "Pinned installs are notify-only.")
                    verify_package_manifest(self.skill_root)
                except PolicyError as exc:
                    selected = "notify"
                    degradation = exc.code
            state.update(
                {
                    "mode": selected,
                    "prompted": True,
                    "installation_id": installation_id(install.source_url, self.skill_root),
                    "source_fingerprint": source_fingerprint(install.source_url),
                    "next_check_at": self._timestamp(),
                    "suspended": False,
                    "last_outcome": "ENABLED_AUTO" if selected == "auto" else "ENABLED_NOTIFY",
                }
            )
            self.store.save(state)
            if degradation:
                return _result(
                    "AUTO_DEGRADED_TO_NOTIFY",
                    state,
                    f"Automatic replacement is unsafe for this install ({degradation}); notification mode was enabled.",
                    action="Repair the install and enable automatic updates again.",
                    current_version=install.version,
                    emit=True,
                )
            return _result(
                "ENABLED_AUTO" if selected == "auto" else "ENABLED_NOTIFY",
                state,
                f"Update mode is now {selected}.",
                current_version=install.version,
                emit=True,
            )

    def disable(self) -> dict[str, object]:
        with self.store.try_lock() as acquired:
            if not acquired:
                return _result("LOCKED", self.store.load(), "Another update-policy action is already running.")
            state = self.store.load()
            state.update(
                {
                    "mode": "off",
                    "prompted": True,
                    "next_check_at": None,
                    "suspended": False,
                    "last_outcome": "DISABLED",
                }
            )
            self.store.save(state)
            return _result("DISABLED", state, "Automatic update activity is disabled.", emit=True)

    def status(self) -> dict[str, object]:
        state = self.store.load()
        return _result("STATUS", state, f"Update mode is {state['mode']}.", emit=True)

    def _save_outcome(
        self,
        state: dict[str, object],
        outcome: str,
        *,
        success: bool,
        suspended: bool = False,
    ) -> None:
        now = self._timestamp()
        state["last_attempt_at"] = now
        state["last_outcome"] = outcome
        state["suspended"] = suspended
        if success:
            state["last_success_at"] = now
            state["next_check_at"] = now + SUCCESS_LEASE_SECONDS
        else:
            state["next_check_at"] = now + TRANSIENT_BACKOFF_SECONDS
        self.store.save(state)

    def _bind(self, state: dict[str, object], install: Installation) -> None:
        expected_source = source_fingerprint(install.source_url)
        expected_install = installation_id(install.source_url, self.skill_root)
        if state["source_fingerprint"] != expected_source or state["installation_id"] != expected_install:
            self._save_outcome(state, "SOURCE_OR_INSTALL_CHANGED", success=False, suspended=True)
            raise PolicyError(
                "SOURCE_OR_INSTALL_CHANGED",
                "The tracked update source or installation identity changed.",
                "Inspect the installation and explicitly re-enable the policy.",
            )

    def maintain(self, *, force: bool = False, notify_only: bool = False) -> dict[str, object]:
        state = self.store.load()
        if not notify_only and state["mode"] == "unconfigured":
            if state["prompted"]:
                return _result("UNCONFIGURED", state, "No update preference is configured.")
            try:
                discover_installation(self.native, self.skill_root)
            except PolicyError:
                return _result(
                    "HOST_MANAGED_OR_UNTRACKED",
                    state,
                    "This surface is not a GitHub CLI-tracked standalone installation.",
                )
            return self.prompt()
        elif not notify_only and state["mode"] == "off":
            return _result("DISABLED", state, "Automatic update activity is disabled.")
        if state["suspended"] and not notify_only:
            return _result(
                "AUTO_SUSPENDED",
                state,
                "Automatic updates are suspended after an integrity failure.",
                action="Inspect the installation and explicitly re-enable automatic updates.",
                emit=True,
            )
        now = self._timestamp()
        next_check = state["next_check_at"]
        if not force and isinstance(next_check, int) and now < next_check:
            return _result("NOT_DUE", state, "The update lease is still active.")

        with self.store.try_lock() as acquired:
            if not acquired:
                return _result("LOCKED", state, "Another update-policy action is already running.")
            state = self.store.load()
            next_check = state["next_check_at"]
            if not force and isinstance(next_check, int) and self._timestamp() < next_check:
                return _result("NOT_DUE", state, "The update lease is still active.")
            try:
                install = discover_installation(self.native, self.skill_root)
                if state["installation_id"] is not None:
                    self._bind(state, install)
                mode = "notify" if notify_only else state["mode"]
                if mode == "notify":
                    result = self.native.update(dry_run=True)
                    if result.returncode != 0:
                        self._save_outcome(state, "TRANSIENT_FAILURE", success=False)
                        return _result(
                            "TRANSIENT_FAILURE",
                            state,
                            "The native update check was unavailable; the skill task is unaffected.",
                            action="Run `gh skill update analyze-project-claims --dry-run` later.",
                            current_version=install.version,
                            emit=force,
                        )
                    self._save_outcome(state, "NOTIFY_CHECKED", success=True)
                    notice = result.stdout.strip() or result.stderr.strip() or None
                    return _result(
                        "NOTIFY_CHECKED",
                        state,
                        "GitHub CLI completed the read-only update check.",
                        current_version=install.version,
                        native_notice=notice,
                        emit=bool(notice) or force,
                    )

                if install.scope != "user":
                    state["mode"] = "notify"
                    self._save_outcome(state, "PROJECT_SCOPE", success=True)
                    return _result(
                        "PROJECT_SCOPE",
                        state,
                        "Project-scope installations are notify-only; notification mode was enabled.",
                        action="Run the native update manually from the owning repository.",
                        current_version=install.version,
                        emit=True,
                    )
                if install.pinned:
                    state["mode"] = "notify"
                    self._save_outcome(state, "PINNED", success=True)
                    return _result(
                        "PINNED",
                        state,
                        "This installation is pinned; notification mode was enabled and the pin was preserved.",
                        action="Keep the pin or update it manually; automatic policy never unpins.",
                        current_version=install.version,
                        emit=True,
                    )
                pre_manifest = verify_package_manifest(self.skill_root)
                update = self.native.update(dry_run=False)
                if update.returncode != 0:
                    try:
                        recovered = discover_installation(self.native, self.skill_root)
                        verify_package_manifest(self.skill_root)
                        self._bind(state, recovered)
                    except PolicyError:
                        self._save_outcome(state, "INVALID_POSTCONDITION", success=False, suspended=True)
                        return _result(
                            "INVALID_POSTCONDITION",
                            state,
                            "The native update failed and the installed package no longer verifies.",
                            action="Reinstall a known release, then explicitly re-enable automatic updates.",
                            current_version=install.version,
                            emit=True,
                        )
                    self._save_outcome(state, "TRANSIENT_FAILURE", success=False)
                    return _result(
                        "TRANSIENT_FAILURE",
                        state,
                        "The native update failed but the prior installed package still verifies.",
                        action="Retry later or run `gh skill update analyze-project-claims` manually.",
                        current_version=install.version,
                        emit=True,
                    )

                try:
                    updated = discover_installation(self.native, self.skill_root)
                    self._bind(state, updated)
                    post_manifest = verify_package_manifest(self.skill_root)
                except PolicyError:
                    self._save_outcome(state, "INVALID_POSTCONDITION", success=False, suspended=True)
                    return _result(
                        "INVALID_POSTCONDITION",
                        state,
                        "The native update completed but the installed package identity or manifest is invalid.",
                        action="Reinstall a known release, then explicitly re-enable automatic updates.",
                        current_version=install.version,
                        emit=True,
                    )
                changed = (
                    updated.version != install.version
                    or updated.tree_sha != install.tree_sha
                    or post_manifest != pre_manifest
                )
                outcome = "UPDATED_NEXT_USE" if changed else "UP_TO_DATE"
                self._save_outcome(state, outcome, success=True)
                return _result(
                    outcome,
                    state,
                    (
                        "A verified update was installed and will be active on the next invocation."
                        if changed
                        else "The installed skill is already current."
                    ),
                    current_version=install.version,
                    installed_version=updated.version,
                    emit=changed,
                )
            except PolicyError as exc:
                if exc.code in {"NATIVE_GH_UNAVAILABLE", "NATIVE_LIST_FAILED", "NATIVE_LIST_INVALID"}:
                    self._save_outcome(state, "TRANSIENT_FAILURE", success=False)
                    return _result(
                        "TRANSIENT_FAILURE",
                        state,
                        "The native update check was unavailable; the skill task is unaffected.",
                        action=exc.action or "Retry later with a GitHub CLI version that supports `gh skill`.",
                        emit=force,
                    )
                if exc.code in {
                    "AMBIGUOUS_INSTALL",
                    "INSTALL_PATH_MISMATCH",
                    "UNTRACKED_INSTALL",
                    "UNSUPPORTED_SOURCE",
                    "SOURCE_MISMATCH",
                    "VERSION_MISMATCH",
                    "PACKAGE_VERSION_INVALID",
                    "PACKAGE_MODIFIED",
                    "PACKAGE_MANIFEST_INVALID",
                    "SOURCE_OR_INSTALL_CHANGED",
                }:
                    if state["mode"] == "auto" and not notify_only:
                        self._save_outcome(state, exc.code, success=False, suspended=True)
                    return _result(exc.code, state, exc.message, action=exc.action, emit=True)
                raise


def render_text(result: dict[str, object]) -> str:
    lines = [f"{result['status']}: {result['message']}"]
    if result.get("current_version"):
        lines.append(f"Current invocation: {result['current_version']}")
    if result.get("installed_version"):
        lines.append(f"Installed for next invocation: {result['installed_version']}")
    if result.get("action"):
        lines.append(f"Action: {result['action']}")
    if result.get("native_notice"):
        lines.append("GitHub CLI notice:")
        lines.append(str(result["native_notice"]))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the analyze-project-claims update policy.")
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-dir", type=Path, default=default_state_directory())
    parser.add_argument("--gh", default="gh", help="GitHub CLI executable (primarily for controlled tests).")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prompt")
    enable_parser = subparsers.add_parser("enable")
    enable_parser.add_argument("--mode", choices=("auto", "notify"), required=True)
    subparsers.add_parser("disable")
    subparsers.add_parser("status")
    subparsers.add_parser("maintain")
    subparsers.add_parser("check-now")
    subparsers.add_parser("verify-package")
    manifest_parser = subparsers.add_parser("build-manifest")
    manifest_parser.add_argument("--write", action="store_true", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = PolicyStore(args.state_dir)
    native = NativeClient((args.gh,), timeout=args.timeout)
    coordinator = UpdateCoordinator(args.skill_root, store, native)
    try:
        if args.command == "prompt":
            result = coordinator.prompt()
        elif args.command == "enable":
            result = coordinator.enable(args.mode)
        elif args.command == "disable":
            result = coordinator.disable()
        elif args.command == "status":
            result = coordinator.status()
        elif args.command == "maintain":
            result = coordinator.maintain()
        elif args.command == "check-now":
            result = coordinator.maintain(force=True, notify_only=True)
        elif args.command == "verify-package":
            digest = verify_package_manifest(args.skill_root)
            state = store.load()
            result = _result("PACKAGE_VERIFIED", state, "Installed package matches its manifest.", native_notice=digest)
        elif args.command == "build-manifest":
            path = write_package_manifest(args.skill_root)
            state = store.load()
            result = _result("MANIFEST_WRITTEN", state, f"Package manifest written to {path}.")
        else:
            parser.error("Unknown command")
            return 2
    except PolicyError as exc:
        state = default_state()
        with contextlib.suppress(PolicyError):
            state = store.load()
        result = _result(exc.code, state, exc.message, action=exc.action, emit=True)
        output = json.dumps(result, sort_keys=True, ensure_ascii=False) if args.format == "json" else render_text(result)
        print(output, file=sys.stderr)
        return 3
    output = json.dumps(result, sort_keys=True, ensure_ascii=False) if args.format == "json" else render_text(result)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

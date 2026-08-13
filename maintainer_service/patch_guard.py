#!/usr/bin/env python3
"""Fail-closed guard for an agent-authored staged patch.

Run this trusted copy after the coding agent and again in the publishing job.
It inspects data through Git only; it never imports or executes candidate code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Sequence


MAX_PATHS = 40
MAX_FILE_BYTES = 512 * 1024
MAX_PATCH_BYTES = 2 * 1024 * 1024
ALLOWED_ROOT_FILES = {"CITATION.cff", "README.md", "VERSION"}
ALLOWED_ROOTS = {"docs", "examples", "skills", "tests"}
ALLOWED_SUFFIXES = {".cff", ".json", ".md", ".py", ".txt", ".yaml", ".yml"}
DENIED_ROOTS = {
    ".github",
    ".git",
    "analytics_service",
    "maintainer_service",
    "reporting_service",
    "validation",
}
DENIED_FILES = {
    ".gitignore",
    ".gitattributes",
    "CLAUDE.md",
    "LICENSE",
    "PUBLISHING.md",
    "SECURITY.md",
    "skills/analyze-project-claims/agents/openai.yaml",
    "skills/analyze-project-claims/references/installation-analytics-event.schema.json",
    "skills/analyze-project-claims/references/installation-analytics-policy.schema.json",
    "skills/analyze-project-claims/references/problem-report-policy.schema.json",
    "skills/analyze-project-claims/references/problem-report.schema.json",
    "skills/analyze-project-claims/scripts/installation_analytics.py",
    "skills/analyze-project-claims/scripts/problem_report.py",
    "skills/analyze-project-claims/scripts/update_policy.py",
}
RELEASE_FILES = {
    "CITATION.cff",
    "VERSION",
    "skills/analyze-project-claims/references/package-manifest.json",
    "skills/analyze-project-claims/references/package-version.json",
}
SKILL_PREFIX = "skills/analyze-project-claims/"
SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class GuardError(RuntimeError):
    """The staged patch violates the maintainer boundary."""


def _git(repo_root: Path, *arguments: str, text: bool = False) -> bytes | str:
    environment = os.environ.copy()
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "-c", "diff.external=", *arguments],
        cwd=repo_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=text,
        encoding="utf-8" if text else None,
        env=environment,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() if text else result.stderr.decode("utf-8", errors="replace").strip()
        raise GuardError(f"Git inspection failed: {detail[:300]}")
    return result.stdout


def _validate_path(raw: str) -> str:
    if not raw or "\\" in raw or "\x00" in raw or any(ord(character) < 32 for character in raw):
        raise GuardError("A changed path has an unsafe representation.")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or str(path) != raw:
        raise GuardError(f"Changed path is not canonical: {raw!r}")
    if raw in DENIED_FILES or path.parts[0] in DENIED_ROOTS:
        raise GuardError(f"Agent changes are forbidden for {raw}.")
    if raw in ALLOWED_ROOT_FILES:
        return raw
    if path.parts[0] not in ALLOWED_ROOTS:
        raise GuardError(f"Agent changes are outside the allowlist: {raw}.")
    if path.parts[0] == "skills" and not raw.startswith(SKILL_PREFIX):
        raise GuardError(f"Agent changes may target only the packaged skill: {raw}.")
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise GuardError(f"Agent changes require a reviewable text extension: {raw}.")
    return raw


def _raw_changes(repo_root: Path) -> list[tuple[str, str, str, str]]:
    payload = _git(repo_root, "diff", "--cached", "--raw", "--no-abbrev", "--no-ext-diff", "-z")
    assert isinstance(payload, bytes)
    parts = payload.split(b"\0")
    changes: list[tuple[str, str, str, str]] = []
    index = 0
    while index < len(parts) and parts[index]:
        try:
            header = parts[index].decode("ascii")
            path = parts[index + 1].decode("utf-8", errors="strict")
        except (IndexError, UnicodeError) as exc:
            raise GuardError("Git returned an invalid changed-path record.") from exc
        index += 2
        fields = header.split()
        if len(fields) != 5 or not fields[0].startswith(":"):
            raise GuardError("Git returned an unexpected raw diff record.")
        old_mode = fields[0][1:]
        new_mode = fields[1]
        status = fields[4]
        if status.startswith(("R", "C")):
            raise GuardError("Renames and copies are not accepted in agent patches.")
        if status not in {"A", "M"}:
            raise GuardError(f"Unsupported Git change status: {status}.")
        changes.append((_validate_path(path), status, old_mode, new_mode))
    return changes


def _read_stage(repo_root: Path, path: str) -> bytes:
    value = _git(repo_root, "show", f":{path}")
    assert isinstance(value, bytes)
    return value


def _read_head(repo_root: Path, path: str) -> str:
    value = _git(repo_root, "show", f"HEAD:{path}", text=True)
    assert isinstance(value, str)
    return value


def _version(value: str, source: str) -> tuple[int, int, int]:
    text = value.strip()
    match = SEMVER_PATTERN.fullmatch(text)
    if match is None:
        raise GuardError(f"{source} must contain a stable three-part SemVer.")
    return tuple(int(part) for part in match.groups())


def _validate_release_binding(repo_root: Path, changed_paths: set[str]) -> str | None:
    skill_payload_changed = any(path.startswith(SKILL_PREFIX) for path in changed_paths)
    release_metadata_changed = bool(changed_paths & RELEASE_FILES)
    if not skill_payload_changed and not release_metadata_changed:
        return None
    missing = RELEASE_FILES - changed_paths
    if missing:
        raise GuardError("Packaged-skill changes require the complete release quartet: " + ", ".join(sorted(missing)))

    old_version = _version(_read_head(repo_root, "VERSION"), "HEAD VERSION")
    new_version_text = _read_stage(repo_root, "VERSION").decode("utf-8", errors="strict").strip()
    new_version = _version(new_version_text, "staged VERSION")
    expected = (old_version[0], old_version[1], old_version[2] + 1)
    if new_version != expected:
        raise GuardError(f"Agent package fixes may bump only the next patch version: {'.'.join(map(str, expected))}.")

    try:
        package_version = json.loads(_read_stage(repo_root, "skills/analyze-project-claims/references/package-version.json"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GuardError("The staged package-version file is not strict JSON.") from exc
    if package_version != {
        "schema_version": 1,
        "skill_name": "analyze-project-claims",
        "version": new_version_text,
    }:
        raise GuardError("The staged package-version contract does not match VERSION.")

    citation = _read_stage(repo_root, "CITATION.cff").decode("utf-8", errors="strict")
    matches = re.findall(r'(?m)^version:\s*["\']?([^"\'\s]+)["\']?\s*$', citation)
    if matches != [new_version_text]:
        raise GuardError("CITATION.cff must contain exactly one version matching VERSION.")
    return new_version_text


def inspect_staged(repo_root: Path) -> dict[str, object]:
    changes = _raw_changes(repo_root)
    if not changes:
        raise GuardError("The agent produced no staged changes.")
    if len(changes) > MAX_PATHS:
        raise GuardError(f"The agent changed more than {MAX_PATHS} paths.")

    paths: list[str] = []
    for path, status, old_mode, new_mode in changes:
        if status == "A" and (old_mode != "000000" or new_mode != "100644"):
            raise GuardError(f"New files must be regular mode-100644 files: {path}.")
        if status == "M" and (old_mode != "100644" or new_mode != "100644"):
            raise GuardError(f"Modified files must remain regular mode-100644 files: {path}.")
        content = _read_stage(repo_root, path)
        if len(content) > MAX_FILE_BYTES:
            raise GuardError(f"A staged file exceeds {MAX_FILE_BYTES} bytes: {path}.")
        if b"\0" in content:
            raise GuardError(f"Binary content is forbidden: {path}.")
        try:
            content.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise GuardError(f"Changed files must be strict UTF-8: {path}.") from exc
        paths.append(path)

    patch = _git(repo_root, "diff", "--cached", "--binary", "--full-index", "--no-ext-diff")
    assert isinstance(patch, bytes)
    if len(patch) > MAX_PATCH_BYTES:
        raise GuardError(f"The staged patch exceeds {MAX_PATCH_BYTES} bytes.")
    version = _validate_release_binding(repo_root, set(paths))
    return {
        "status": "PASS",
        "path_count": len(paths),
        "paths": sorted(paths),
        "patch_bytes": len(patch),
        "candidate_version": version,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect an agent-authored staged patch without executing it.")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--staged", action="store_true", help="Required acknowledgement that the Git index is inspected.")
    parser.add_argument("--json-out", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not args.staged:
            raise GuardError("Pass --staged; working-tree-only changes are intentionally ignored.")
        result = inspect_staged(args.repo_root.resolve())
        output = json.dumps(result, sort_keys=True)
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(output + "\n", encoding="utf-8", newline="\n")
        print(output)
        return 0
    except (GuardError, OSError, UnicodeError, ValueError) as exc:
        output = json.dumps({"status": "REJECTED", "message": str(exc)}, sort_keys=True)
        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            args.json_out.write_text(output + "\n", encoding="utf-8", newline="\n")
        print(output)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

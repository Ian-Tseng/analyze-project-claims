#!/usr/bin/env python3
"""Scaffold and diagnose Ian-Tseng managed-skill repair callers.

This client is deliberately policy-only. It never runs a repair agent, edits an
issue, creates an environment, pushes a branch, or publishes a pull request.
Repository mutation is limited to two deterministic files and always requires
``--apply``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from _internal.safe_process import ExecutableResolutionError, resolve_executable


PROTOCOL = "ian-tseng-managed-skill-repair/v1"
POLICY_PATH = Path(".github/managed-skill-policy.json")
CALLER_PATH = Path(".github/workflows/managed-skill-repair.yml")
WORKFLOW_REPOSITORY = "Ian-Tseng/analyze-project-claims"
WORKFLOW_PATH = ".github/workflows/managed-skill-repair.yml"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_PATTERN = re.compile(r"^Ian-Tseng/[A-Za-z0-9_.-]+$")
SKILL_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")
PROFILE_IDS = {"python-unittest-package-v1", "python-pytest-package-v1"}
TOP_LEVEL_KEYS = {
    "schema_version", "protocol", "enabled", "repository", "skill",
    "validation", "triage", "environments", "publication",
    "compatibility", "workflow",
}
HARD_DENIED = {
    ".github/workflows",
    ".github/actions",
    ".github/managed-skill-policy.json",
    ".gitmodules",
    "LICENSE",
    "PUBLISHING.md",
    "SECURITY.md",
    "validation",
}


class FleetError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FleetError("POLICY_DUPLICATE_KEY", f"Managed policy contains duplicate key {key!r}.")
        result[key] = value
    return result


def read_json(path: Path, *, limit: int = 128 * 1024) -> object:
    try:
        if path.is_symlink() or not path.is_file():
            raise FleetError("POLICY_UNSAFE", f"Expected an ordinary policy file at {path}.")
        raw = path.read_bytes()
        if len(raw) > limit:
            raise FleetError("POLICY_TOO_LARGE", f"Policy exceeds {limit} bytes.")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except FleetError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FleetError("POLICY_INVALID_JSON", f"Policy is not strict UTF-8 JSON: {path}.") from exc


def _object(value: object, keys: set[str], source: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise FleetError("POLICY_SHAPE", f"{source} has unknown or missing fields.")
    return value


def _safe_path(value: object, source: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 180 or "\\" in value or "\x00" in value:
        raise FleetError("POLICY_PATH", f"{source} is not a bounded repository-relative path.")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value or any(not part for part in path.parts):
        raise FleetError("POLICY_PATH", f"{source} is not a canonical repository-relative path.")
    if value.casefold() != value.lower().casefold():
        raise FleetError("POLICY_PATH", f"{source} has unstable Unicode case identity.")
    return value


def _path_list(value: object, source: str, *, minimum: int, maximum: int) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise FleetError("POLICY_SHAPE", f"{source} must contain {minimum}..{maximum} paths.")
    result = [_safe_path(item, source) for item in value]
    if len({item.casefold() for item in result}) != len(result):
        raise FleetError("POLICY_COLLISION", f"{source} contains duplicate or case-colliding paths.")
    return result


def validate_policy(value: object) -> dict[str, object]:
    policy = _object(value, TOP_LEVEL_KEYS, "policy")
    if policy["schema_version"] != 1 or policy["protocol"] != PROTOCOL or not isinstance(policy["enabled"], bool):
        raise FleetError("POLICY_PROTOCOL", "Managed policy protocol or enabled state is invalid.")

    repository = _object(policy["repository"], {"id", "full_name", "default_branch"}, "repository")
    if not isinstance(repository["id"], int) or isinstance(repository["id"], bool) or repository["id"] < 1:
        raise FleetError("POLICY_REPOSITORY", "Repository ID must be a positive GitHub numeric ID.")
    if not isinstance(repository["full_name"], str) or not REPOSITORY_PATTERN.fullmatch(repository["full_name"]):
        raise FleetError("POLICY_REPOSITORY", "Managed repositories are restricted to the Ian-Tseng owner boundary.")
    if not isinstance(repository["default_branch"], str) or not BRANCH_PATTERN.fullmatch(repository["default_branch"]):
        raise FleetError("POLICY_REPOSITORY", "Default branch identity is invalid.")

    skill = _object(
        policy["skill"],
        {"name", "package_roots", "allowed_roots", "denied_paths", "version_files"},
        "skill",
    )
    if not isinstance(skill["name"], str) or not SKILL_PATTERN.fullmatch(skill["name"]):
        raise FleetError("POLICY_SKILL", "Skill name is invalid.")
    package_roots = _path_list(skill["package_roots"], "package_roots", minimum=1, maximum=4)
    allowed_roots = _path_list(skill["allowed_roots"], "allowed_roots", minimum=1, maximum=16)
    denied_paths = _path_list(skill["denied_paths"], "denied_paths", minimum=0, maximum=32)
    version_files = _path_list(skill["version_files"], "version_files", minimum=2, maximum=12)
    if f"skills/{skill['name']}" not in package_roots:
        raise FleetError("POLICY_SKILL", "The canonical skill package root is required.")
    if not set(HARD_DENIED).issubset(set(denied_paths)):
        raise FleetError("POLICY_DENIAL", "Policy must preserve every central hard-denied path.")
    if any(any(root == denied or root.startswith(denied + "/") for denied in HARD_DENIED) for root in allowed_roots):
        raise FleetError("POLICY_DENIAL", "Allowed roots overlap a central hard-denied path.")
    if not set(package_roots).issubset(set(allowed_roots)):
        raise FleetError("POLICY_SKILL", "Every package root must also be an allowed root.")
    if not all(any(path == root or path.startswith(root + "/") for root in allowed_roots) or path in {"VERSION", "CITATION.cff"} for path in version_files):
        raise FleetError("POLICY_SKILL", "Version files must be inside allowed roots or approved root identities.")

    validation = _object(policy["validation"], {"profile"}, "validation")
    if validation["profile"] not in PROFILE_IDS:
        raise FleetError("POLICY_VALIDATION", "Validation profile is not a central named profile.")
    triage = _object(policy["triage"], {"label", "actors"}, "triage")
    if triage != {"label": "managed-repair-ready", "actors": ["Ian-Tseng"]}:
        raise FleetError("POLICY_TRIAGE", "Triage is restricted to Ian-Tseng and managed-repair-ready.")
    environments = _object(policy["environments"], {"agent", "publish"}, "environments")
    if environments != {"agent": "managed-repair-agent", "publish": "managed-repair-publish"}:
        raise FleetError("POLICY_ENVIRONMENT", "Both fixed protected environments are required.")
    publication = _object(policy["publication"], {"draft_only"}, "publication")
    if publication != {"draft_only": True}:
        raise FleetError("POLICY_PUBLICATION", "Managed publication is draft-only.")
    compatibility = _object(policy["compatibility"], {"minimum", "maximum"}, "compatibility")
    if compatibility != {"minimum": "1.0", "maximum": "1.x"}:
        raise FleetError("POLICY_COMPATIBILITY", "Unsupported managed-protocol compatibility range.")
    workflow = _object(policy["workflow"], {"repository", "path", "sha"}, "workflow")
    if workflow["repository"] != WORKFLOW_REPOSITORY or workflow["path"] != WORKFLOW_PATH:
        raise FleetError("POLICY_WORKFLOW", "Policy must use the canonical analyzer workflow.")
    if not isinstance(workflow["sha"], str) or not SHA_PATTERN.fullmatch(workflow["sha"]):
        raise FleetError("POLICY_WORKFLOW", "Workflow must be pinned to one full lowercase commit SHA.")
    return json.loads(canonical_bytes(policy).decode("ascii"))


def build_policy(
    *, repository: str, repository_id: int, skill: str, package_root: str,
    workflow_sha: str, validation_profile: str, repair_enabled: bool,
) -> dict[str, object]:
    value = {
        "schema_version": 1,
        "protocol": PROTOCOL,
        "enabled": repair_enabled,
        "repository": {"id": repository_id, "full_name": repository, "default_branch": "main"},
        "skill": {
            "name": skill,
            "package_roots": [package_root],
            "allowed_roots": ["CITATION.cff", "README.md", "VERSION", "docs", package_root, "tests"],
            "denied_paths": sorted(HARD_DENIED),
            "version_files": [
                "CITATION.cff", "VERSION", f"{package_root}/references/package-manifest.json",
                f"{package_root}/references/package-version.json",
            ],
        },
        "validation": {"profile": validation_profile},
        "triage": {"label": "managed-repair-ready", "actors": ["Ian-Tseng"]},
        "environments": {"agent": "managed-repair-agent", "publish": "managed-repair-publish"},
        "publication": {"draft_only": True},
        "compatibility": {"minimum": "1.0", "maximum": "1.x"},
        "workflow": {"repository": WORKFLOW_REPOSITORY, "path": WORKFLOW_PATH, "sha": workflow_sha},
    }
    return validate_policy(value)


def render_policy(policy: Mapping[str, object]) -> str:
    return json.dumps(validate_policy(dict(policy)), ensure_ascii=True, sort_keys=True, indent=2) + "\n"


def render_caller(workflow_sha: str) -> str:
    if not SHA_PATTERN.fullmatch(workflow_sha):
        raise FleetError("POLICY_WORKFLOW", "Caller workflow requires a full lowercase commit SHA.")
    return f'''name: managed skill repair caller

on:
  issues:
    types: [labeled]
  workflow_dispatch:
    inputs:
      dry_run:
        description: Validate hosted configuration without running an agent or publishing.
        required: true
        default: true
        type: boolean

permissions:
  contents: write
  issues: write
  pull-requests: write

jobs:
  managed-repair:
    uses: Ian-Tseng/analyze-project-claims/.github/workflows/managed-skill-repair.yml@{workflow_sha}
    with:
      policy-path: .github/managed-skill-policy.json
      dry-run: ${{{{ github.event_name == 'workflow_dispatch' && inputs.dry_run }}}}
    secrets:
      OPENAI_API_KEY: ${{{{ secrets.OPENAI_API_KEY }}}}
'''


def _envelope(status: str, code: str, *, effect: str, changed: bool, retryable: bool = False,
              next_action: str | None = None, **extra: object) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": 1, "status": status, "code": code, "effect": effect,
        "changed": changed, "retryable": retryable, "next_action": next_action,
        "docs": "docs/MANAGED_FLEET_QUICKSTART.md",
    }
    result.update(extra)
    return result


def _write_exact(path: Path, content: str) -> bool:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise FleetError("TARGET_UNSAFE", f"Refusing non-regular target {path}.")
        if path.read_text(encoding="utf-8") == content:
            return False
        raise FleetError("TARGET_CONFLICT", f"Refusing to overwrite divergent file {path}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return True


def _load_local(root: Path) -> tuple[dict[str, object], str]:
    policy = validate_policy(read_json(root / POLICY_PATH))
    caller_path = root / CALLER_PATH
    if caller_path.is_symlink() or not caller_path.is_file():
        raise FleetError("CALLER_MISSING", f"Managed caller is missing at {CALLER_PATH.as_posix()}.")
    caller = caller_path.read_text(encoding="utf-8")
    expected = render_caller(policy["workflow"]["sha"])
    if caller != expected:
        raise FleetError("CALLER_DRIFT", "Managed caller does not exactly match its policy pin.")
    return policy, caller


def _init(args: argparse.Namespace) -> dict[str, object]:
    root = args.repo_root.resolve()
    policy = build_policy(
        repository=args.repository, repository_id=args.repository_id, skill=args.skill,
        package_root=args.package_root, workflow_sha=args.workflow_sha,
        validation_profile=args.validation_profile, repair_enabled=args.enable_repair,
    )
    files = {
        POLICY_PATH.as_posix(): render_policy(policy),
        CALLER_PATH.as_posix(): render_caller(args.workflow_sha),
    }
    if not args.apply:
        return _envelope("PREVIEW_READY", "LOCAL_PREVIEW", effect="NONE", changed=False,
                         next_action="Rerun with --apply after reviewing the two exact files.",
                         files=files, policy_sha256=digest(policy))
    changed = False
    for relative, content in files.items():
        changed = _write_exact(root / Path(relative), content) or changed
    return _envelope("LOCAL_READY" if changed else "ALREADY_CONFIGURED", "LOCAL_READY",
                     effect="WROTE_TWO_FILES" if changed else "NONE", changed=changed,
                     next_action="Run validate, then provision the two protected environments.",
                     files=sorted(files), policy_sha256=digest(policy))


def _validate(args: argparse.Namespace) -> dict[str, object]:
    policy, _ = _load_local(args.repo_root.resolve())
    missing = [path for path in policy["skill"]["package_roots"] if not (args.repo_root / path).is_dir()]
    if missing:
        raise FleetError("PACKAGE_ROOT_MISSING", "Configured package roots are missing: " + ", ".join(missing))
    return _envelope("LOCAL_READY", "LOCAL_READY", effect="NONE", changed=False,
                     next_action="Run doctor --local; hosted protection and canary remain separate gates.",
                     policy_sha256=digest(policy), workflow_sha=policy["workflow"]["sha"])


def _doctor_local(args: argparse.Namespace) -> dict[str, object]:
    policy, _ = _load_local(args.repo_root.resolve())
    return _envelope("LOCAL_READY", "LOCAL_READY", effect="NONE", changed=False,
                     next_action="Provision managed-repair-agent and managed-repair-publish, then run a dry canary.",
                     policy_sha256=digest(policy), workflow_sha=policy["workflow"]["sha"],
                     repair_enabled=policy["enabled"], hosted="NOT_OBSERVED")


def _gh_json(endpoint: str) -> tuple[object | None, str | None]:
    try:
        executable = resolve_executable("gh")
    except ExecutableResolutionError as exc:
        raise FleetError("GITHUB_CLI_UNAVAILABLE", str(exc), retryable=True) from exc
    result = subprocess.run(
        [executable, "api", endpoint],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    if result.returncode:
        return None, result.stderr[:4096].decode("utf-8", errors="replace").splitlines()[0] if result.stderr else "unavailable"
    if len(result.stdout) > 1024 * 1024:
        raise FleetError("GITHUB_RESPONSE_TOO_LARGE", "GitHub configuration response exceeded one MiB.")
    try:
        return json.loads(result.stdout.decode("utf-8")), None
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FleetError("GITHUB_RESPONSE_INVALID", "GitHub CLI returned invalid JSON.", retryable=True) from exc


def _protected_environment(value: object) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("protection_rules"), list):
        return False
    for rule in value["protection_rules"]:
        if isinstance(rule, dict) and rule.get("type") == "required_reviewers":
            reviewers = rule.get("reviewers")
            if isinstance(reviewers, list) and reviewers:
                return True
    return False


def _doctor_repo(args: argparse.Namespace) -> dict[str, object]:
    policy, _ = _load_local(args.repo_root.resolve())
    repository = policy["repository"]["full_name"]
    if args.repo != repository:
        raise FleetError("REPOSITORY_MISMATCH", "Requested repository does not match local policy.")
    endpoints = {
        "repository": f"repos/{repository}",
        "agent_environment": f"repos/{repository}/environments/managed-repair-agent",
        "publish_environment": f"repos/{repository}/environments/managed-repair-publish",
        "actions": f"repos/{repository}/actions/permissions",
        "workflow_permissions": f"repos/{repository}/actions/permissions/workflow",
        "secret": f"repos/{repository}/actions/secrets/OPENAI_API_KEY",
        "label": f"repos/{repository}/labels/managed-repair-ready",
        "runs": f"repos/{repository}/actions/workflows/managed-skill-repair.yml/runs?event=workflow_dispatch&per_page=1",
    }
    observed: dict[str, object | None] = {}
    unavailable: list[str] = []
    for name, endpoint in endpoints.items():
        value, error = _gh_json(endpoint)
        observed[name] = value
        if error:
            unavailable.append(name)
    repo_value = observed["repository"]
    identity = isinstance(repo_value, dict) and repo_value.get("id") == policy["repository"]["id"] and repo_value.get("full_name") == repository
    actions = observed["actions"]
    actions_enabled = isinstance(actions, dict) and actions.get("enabled") is True
    workflow_permissions = observed["workflow_permissions"]
    pr_creation = isinstance(workflow_permissions, dict) and workflow_permissions.get("can_approve_pull_request_reviews") is True
    runs = observed["runs"]
    run_list = runs.get("workflow_runs") if isinstance(runs, dict) else None
    last_run = run_list[0] if isinstance(run_list, list) and run_list and isinstance(run_list[0], dict) else None
    canary = "PASS" if last_run and last_run.get("conclusion") == "success" else "NOT_OBSERVED"
    checks = {
        "repository_identity": identity,
        "agent_environment_protected": _protected_environment(observed["agent_environment"]),
        "publish_environment_protected": _protected_environment(observed["publish_environment"]),
        "actions_enabled": actions_enabled,
        "actions_pr_creation_enabled": pr_creation,
        "openai_secret_named": isinstance(observed["secret"], dict) and observed["secret"].get("name") == "OPENAI_API_KEY",
        "trigger_label_exists": isinstance(observed["label"], dict) and observed["label"].get("name") == "managed-repair-ready",
    }
    configured = all(checks.values())
    ready = configured and canary == "PASS"
    return _envelope(
        "HOSTED_READY" if ready else "HOSTED_NOT_READY",
        "HOSTED_READY" if ready else "HOSTED_GATES_PENDING",
        effect="NONE",
        changed=False,
        retryable=bool(unavailable),
        next_action=(
            "Run the method/venue dry canary, then enable repair in canary order."
            if ready
            else "Provision or repair the false checks, then run workflow_dispatch dry_run=true."
        ),
        repository=repository,
        checks=checks,
        unavailable=unavailable,
        last_canary=canary,
        last_canary_url=last_run.get("html_url") if last_run else None,
        workflow_sha=policy["workflow"]["sha"],
        policy_sha256=digest(policy),
    )


def _disable(args: argparse.Namespace) -> dict[str, object]:
    root = args.repo_root.resolve()
    policy = validate_policy(read_json(root / POLICY_PATH))
    if not policy["enabled"]:
        return _envelope("ALREADY_DISABLED", "DISABLED", effect="NONE", changed=False,
                         next_action="Keep the trigger label removed and environments locked.")
    disabled = dict(policy)
    disabled["enabled"] = False
    content = render_policy(disabled)
    if not args.apply:
        return _envelope("PREVIEW_READY", "DISABLE_PREVIEW", effect="NONE", changed=False,
                         next_action="Remove the trigger label, lock both environments, then rerun with --apply.",
                         policy=disabled)
    path = root / POLICY_PATH
    path.write_text(content, encoding="utf-8", newline="\n")
    return _envelope("DISABLED", "DISABLED", effect="POLICY_DISABLED", changed=True,
                     next_action="Commit this caller-owned kill-switch change for review.")


def _rollback(args: argparse.Namespace) -> dict[str, object]:
    policy, _ = _load_local(args.repo_root.resolve())
    return _envelope("PLAN_READY", "ROLLBACK_PLAN", effect="NONE", changed=False,
                     next_action="Review and commit a policy/caller rollback to the last compatible full SHA.",
                     actions=["remove managed-repair-ready", "lock both environments", "set enabled=false",
                              "replace policy and caller SHA together", "run validate and dry canary"],
                     current_workflow_sha=policy["workflow"]["sha"])


def _canary(args: argparse.Namespace) -> dict[str, object]:
    if not args.dry_run:
        raise FleetError("CANARY_MUTATION_UNSUPPORTED", "This local client only previews hosted canaries.")
    policy, _ = _load_local(args.repo_root.resolve())
    return _envelope("CANARY_PREVIEW", "CANARY_DRY_RUN", effect="NONE", changed=False,
                     next_action="Run the caller workflow_dispatch dry-run after hosted protections are configured.",
                     gates=["policy", "pin", "agent environment", "publish environment", "Actions PR setting"],
                     workflow_sha=policy["workflow"]["sha"])


def _reconcile(args: argparse.Namespace) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{64}", args.authorization_id):
        raise FleetError("AUTHORIZATION_ID_INVALID", "Authorization ID must be one lowercase SHA-256 value.")
    return _envelope("RECONCILIATION_REQUIRED", "REMOTE_STATE_NOT_OBSERVED", effect="NONE", changed=False,
                     retryable=True,
                     next_action="Use the hosted workflow run to reconcile branch, PR, and issue-comment state.",
                     authorization_id=args.authorization_id)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--format", choices=("text", "json"), default="text")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--repo-root", type=Path, default=Path("."))
    init.add_argument("--repository", required=True)
    init.add_argument("--repository-id", type=int, required=True)
    init.add_argument("--skill", required=True)
    init.add_argument("--package-root", required=True)
    init.add_argument("--workflow-sha", required=True)
    init.add_argument("--validation-profile", choices=sorted(PROFILE_IDS), required=True)
    init.add_argument("--enable-repair", action="store_true")
    init.add_argument("--apply", action="store_true")
    for name in ("validate", "pin-status"):
        command = commands.add_parser(name)
        command.add_argument("--repo-root", type=Path, default=Path("."))
    doctor = commands.add_parser("doctor")
    doctor.add_argument("--local", action="store_true")
    doctor.add_argument("--repo")
    doctor.add_argument("--repo-root", type=Path, default=Path("."))
    canary = commands.add_parser("canary")
    canary.add_argument("--dry-run", action="store_true", required=True)
    canary.add_argument("--repo-root", type=Path, default=Path("."))
    disable = commands.add_parser("disable")
    disable.add_argument("--repo-root", type=Path, default=Path("."))
    disable.add_argument("--apply", action="store_true")
    rollback = commands.add_parser("rollback-plan")
    rollback.add_argument("--repo-root", type=Path, default=Path("."))
    reconcile = commands.add_parser("reconcile-publication")
    reconcile.add_argument("--authorization-id", required=True)
    return result


def render_text(result: Mapping[str, object]) -> str:
    lines = [f"{result['status']}: {result['code']}", f"Effect: {result['effect']}"]
    if result.get("next_action"):
        lines.append(f"Next: {result['next_action']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            result = _init(args)
        elif args.command in {"validate", "pin-status"}:
            result = _validate(args)
        elif args.command == "doctor":
            if not args.local and not args.repo:
                raise FleetError("DOCTOR_SCOPE_REQUIRED", "Choose --local or --repo OWNER/REPO.")
            result = _doctor_repo(args) if args.repo else _doctor_local(args)
        elif args.command == "canary":
            result = _canary(args)
        elif args.command == "disable":
            result = _disable(args)
        elif args.command == "rollback-plan":
            result = _rollback(args)
        elif args.command == "reconcile-publication":
            result = _reconcile(args)
        else:
            raise FleetError("COMMAND_INVALID", "Unsupported command.")
        print(json.dumps(result, sort_keys=True) if args.format == "json" else render_text(result))
        return 4 if result["code"] == "REMOTE_STATE_NOT_OBSERVED" else 0
    except FleetError as exc:
        result = _envelope("REFUSED", exc.code, effect="NONE", changed=False,
                           retryable=exc.retryable, next_action=exc.message)
        print(json.dumps(result, sort_keys=True) if args.format == "json" else render_text(result), file=sys.stderr)
        return 3 if exc.retryable else 2
    except OSError as exc:
        result = _envelope("FAILED", "LOCAL_IO_FAILED", effect="UNKNOWN", changed=False,
                           retryable=False, next_action=str(exc))
        print(json.dumps(result, sort_keys=True) if args.format == "json" else render_text(result), file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())

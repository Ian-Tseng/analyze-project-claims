#!/usr/bin/env python3
"""Consent-gated activation analytics for analyze-project-claims.

The client sends only a random installation UUID, product/version identity,
event type, event UUID, and timestamp. It never sends project content, user
identity, prompts, logs, report data, paths, or host diagnostics.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib import error, parse, request


PRODUCT = "analyze-project-claims"
SCHEMA_VERSION = 1
POLICY_SCHEMA_VERSION = 1
ENDPOINT_ENV = "ANALYZE_PROJECT_CLAIMS_ANALYTICS_ENDPOINT"
TOKEN_ENV = "ANALYZE_PROJECT_CLAIMS_ANALYTICS_TOKEN"
MAX_EVENT_BYTES = 2 * 1024
MAX_RESPONSE_BYTES = 8 * 1024
MODES = {"unconfigured", "off", "on"}
EVENT_TYPES = {"activated", "version_changed"}
EVENT_KEYS = {
    "schema_version",
    "event_id",
    "product",
    "product_version",
    "installation_id",
    "event_type",
    "occurred_at",
}
POLICY_KEYS = {
    "schema_version",
    "mode",
    "prompted",
    "endpoint",
    "installation_id",
    "last_sent_version",
    "last_event_id",
    "last_success_at",
    "last_outcome",
    "pending_event",
}
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
RFC3339_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
OUTCOME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class AnalyticsError(RuntimeError):
    def __init__(self, code: str, message: str, action: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action


def default_state_directory() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / PRODUCT if base else Path.home() / "AppData" / "Local" / PRODUCT
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / PRODUCT
    base = os.environ.get("XDG_STATE_HOME")
    return Path(base) / PRODUCT if base else Path.home() / ".local" / "state" / PRODUCT


def canonical_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be a UUID string.")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be a UUID string.") from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise AnalyticsError("ANALYTICS_INVALID", f"{field} must be a canonical UUIDv4 string.")
    return value.lower()


def validate_endpoint(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Analytics requires an owner API endpoint.")
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
        raise AnalyticsError(
            "ANALYTICS_POLICY_INVALID",
            "Analytics endpoint must be HTTPS, except localhost, and contain no credentials or query data.",
        )
    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1/analytics/events"
    if path != "/v1/analytics/events":
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Analytics endpoint path must be /v1/analytics/events.")
    return parse.urlunparse(parsed._replace(path=path))


def default_policy() -> dict[str, object]:
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "mode": "unconfigured",
        "prompted": False,
        "endpoint": None,
        "installation_id": None,
        "last_sent_version": None,
        "last_event_id": None,
        "last_success_at": None,
        "last_outcome": "NEVER",
        "pending_event": None,
    }


def validate_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != POLICY_KEYS:
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Analytics policy has unknown or missing fields.")
    policy = dict(value)
    if policy["schema_version"] != POLICY_SCHEMA_VERSION or policy["mode"] not in MODES:
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Analytics policy version or mode is invalid.")
    if not isinstance(policy["prompted"], bool):
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Analytics prompted state is invalid.")
    if policy["endpoint"] is not None:
        policy["endpoint"] = validate_endpoint(policy["endpoint"])
    if policy["mode"] == "on" and policy["endpoint"] is None:
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Enabled analytics requires an endpoint.")
    if policy["installation_id"] is not None:
        policy["installation_id"] = canonical_uuid(policy["installation_id"], "installation_id")
    if policy["mode"] == "on" and policy["installation_id"] is None:
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Enabled analytics requires an installation ID.")
    for field in ("last_sent_version",):
        item = policy[field]
        if item is not None and (not isinstance(item, str) or not SEMVER_PATTERN.fullmatch(item)):
            raise AnalyticsError("ANALYTICS_POLICY_INVALID", f"{field} is invalid.")
    if policy["last_event_id"] is not None:
        policy["last_event_id"] = canonical_uuid(policy["last_event_id"], "last_event_id")
    if policy["last_success_at"] is not None and (
        not isinstance(policy["last_success_at"], int)
        or isinstance(policy["last_success_at"], bool)
        or policy["last_success_at"] < 0
    ):
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "last_success_at is invalid.")
    if not isinstance(policy["last_outcome"], str) or not OUTCOME_PATTERN.fullmatch(policy["last_outcome"]):
        raise AnalyticsError("ANALYTICS_POLICY_INVALID", "last_outcome is invalid.")
    if policy["pending_event"] is not None:
        policy["pending_event"] = validate_event(policy["pending_event"])
        if policy["installation_id"] != policy["pending_event"]["installation_id"]:
            raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Pending event belongs to another installation.")
    return policy


class PolicyStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.expanduser().absolute()
        self.path = self.directory / "installation-analytics-policy.json"

    def _prepare(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise AnalyticsError("ANALYTICS_POLICY_UNSAFE", "Analytics state directory cannot be a symbolic link.")
        if os.name != "nt":
            os.chmod(self.directory, 0o700)

    def load(self, *, create: bool = False) -> dict[str, object]:
        if not self.path.exists():
            policy = default_policy()
            if create:
                self.save(policy)
            return policy
        if self.path.is_symlink() or not self.path.is_file():
            raise AnalyticsError("ANALYTICS_POLICY_UNSAFE", "Analytics policy path is not a regular file.")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Analytics policy is not strict JSON.") from exc
        return validate_policy(value)

    def save(self, policy: Mapping[str, object]) -> None:
        self._prepare()
        validated = validate_policy(dict(policy))
        payload = (json.dumps(validated, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".analytics-policy-", suffix=".tmp", dir=self.directory)
        temporary = Path(temporary_name)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
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


def package_version(skill_root: Path) -> str:
    path = skill_root / "references" / "package-version.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AnalyticsError("PACKAGE_VERSION_INVALID", "Package version is unavailable.") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "skill_name", "version"}
        or value["schema_version"] != 1
        or value["skill_name"] != PRODUCT
        or not isinstance(value["version"], str)
        or not SEMVER_PATTERN.fullmatch(value["version"])
    ):
        raise AnalyticsError("PACKAGE_VERSION_INVALID", "Package version is invalid.")
    return value["version"]


def build_event(
    *,
    installation_id: str,
    product_version: str,
    event_type: str,
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    if not SEMVER_PATTERN.fullmatch(product_version):
        raise AnalyticsError("ANALYTICS_INVALID", "Product version must be SemVer.")
    if event_type not in EVENT_TYPES:
        raise AnalyticsError("ANALYTICS_INVALID", "Analytics event type is invalid.")
    timestamp = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc).replace(microsecond=0)
    return validate_event(
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(uuid.uuid4()),
            "product": PRODUCT,
            "product_version": product_version,
            "installation_id": canonical_uuid(installation_id, "installation_id"),
            "event_type": event_type,
            "occurred_at": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )


def validate_event(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != EVENT_KEYS:
        raise AnalyticsError("ANALYTICS_INVALID", "Analytics event has unknown or missing fields.")
    event = dict(value)
    if event["schema_version"] != SCHEMA_VERSION or event["product"] != PRODUCT:
        raise AnalyticsError("ANALYTICS_INVALID", "Analytics schema or product is invalid.")
    event["event_id"] = canonical_uuid(event["event_id"], "event_id")
    event["installation_id"] = canonical_uuid(event["installation_id"], "installation_id")
    if not isinstance(event["product_version"], str) or not SEMVER_PATTERN.fullmatch(event["product_version"]):
        raise AnalyticsError("ANALYTICS_INVALID", "Analytics product version is invalid.")
    if event["event_type"] not in EVENT_TYPES:
        raise AnalyticsError("ANALYTICS_INVALID", "Analytics event type is invalid.")
    if not isinstance(event["occurred_at"], str) or not RFC3339_PATTERN.fullmatch(event["occurred_at"]):
        raise AnalyticsError("ANALYTICS_INVALID", "Analytics timestamp is invalid.")
    encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_EVENT_BYTES:
        raise AnalyticsError("ANALYTICS_INVALID", "Analytics event exceeds the maximum size.")
    return event


class ApiTransport:
    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        opener: Callable[..., object] = request.urlopen,
    ) -> None:
        self.endpoint = validate_endpoint(endpoint)
        self.token = token if token is not None else os.environ.get(TOKEN_ENV)
        self.opener = opener

    def _post(self, endpoint: str, value: Mapping[str, object]) -> dict[str, object]:
        data = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            if not 20 <= len(self.token) <= 512 or re.search(r"\s", self.token):
                raise AnalyticsError("ANALYTICS_TOKEN_INVALID", "Analytics API token is invalid.")
            headers["Authorization"] = f"Bearer {self.token}"
        req = request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with self.opener(req, timeout=15) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                status = getattr(response, "status", 200)
        except error.HTTPError as exc:
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            message = "Owner analytics API rejected the request."
            with contextlib.suppress(UnicodeError, json.JSONDecodeError):
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
                    message = parsed["message"]
            raise AnalyticsError("ANALYTICS_DELIVERY_FAILED", message) from exc
        except (error.URLError, OSError, TimeoutError) as exc:
            raise AnalyticsError("ANALYTICS_DELIVERY_FAILED", "Owner analytics API is unavailable.") from exc
        if status not in {200, 201} or len(raw) > MAX_RESPONSE_BYTES:
            raise AnalyticsError("ANALYTICS_DELIVERY_FAILED", "Owner analytics API returned an invalid response.")
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AnalyticsError("ANALYTICS_DELIVERY_FAILED", "Owner analytics API returned invalid JSON.") from exc
        if not isinstance(result, dict):
            raise AnalyticsError("ANALYTICS_DELIVERY_FAILED", "Owner analytics API returned an invalid object.")
        return result

    def send(self, event: Mapping[str, object]) -> dict[str, object]:
        validated = validate_event(dict(event))
        result = self._post(self.endpoint, validated)
        if result.get("event_id") != validated["event_id"] or result.get("status") not in {"recorded", "duplicate"}:
            raise AnalyticsError("ANALYTICS_DELIVERY_FAILED", "Owner analytics receipt is invalid.")
        return result

    def erase(self, installation_id: str) -> dict[str, object]:
        canonical = canonical_uuid(installation_id, "installation_id")
        endpoint = self.endpoint[: -len("events")] + "erasures"
        result = self._post(endpoint, {"installation_id": canonical})
        if result.get("status") != "deleted":
            raise AnalyticsError("ANALYTICS_DELIVERY_FAILED", "Owner analytics deletion receipt is invalid.")
        return result


def result(status: str, policy: Mapping[str, object], message: str, **extra: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "status": status,
        "mode": policy["mode"],
        "message": message,
        "action": None,
    }
    value.update(extra)
    return value


class AnalyticsClient:
    def __init__(
        self,
        skill_root: Path,
        store: PolicyStore,
        *,
        transport_factory: Callable[[str], object] | None = None,
        now_datetime: Callable[[], datetime] | None = None,
        now_epoch: Callable[[], float] = time.time,
    ) -> None:
        self.skill_root = skill_root.resolve()
        self.store = store
        self.transport_factory = transport_factory or (lambda endpoint: ApiTransport(endpoint))
        self.now_datetime = now_datetime
        self.now_epoch = now_epoch

    def prompt(self) -> dict[str, object]:
        policy = self.store.load(create=True)
        if policy["mode"] != "unconfigured" or policy["prompted"]:
            return result("NO_PROMPT", policy, "Analytics preference is already known or the prompt was already shown.")
        policy["prompted"] = True
        policy["last_outcome"] = "CONSENT_REQUIRED"
        self.store.save(policy)
        return result(
            "CONSENT_REQUIRED",
            policy,
            (
                "Share anonymous activation receipts with the owner? Each receipt contains only a random installation "
                "ID, product version, event type, event ID, and timestamp. It never contains user identity, project "
                "content, prompts, logs, paths, findings, reports, or diagnostics."
            ),
            action="Say `enable anonymous installation analytics` or `decline installation analytics`.",
            emit=True,
        )

    def enable(self, endpoint: str) -> dict[str, object]:
        policy = self.store.load(create=True)
        policy.update(
            {
                "mode": "on",
                "prompted": True,
                "endpoint": validate_endpoint(endpoint),
                "installation_id": policy["installation_id"] or str(uuid.uuid4()),
                "last_outcome": "ENABLED",
            }
        )
        self.store.save(policy)
        return result(
            "ENABLED",
            policy,
            "Anonymous installation analytics is enabled. Nothing was sent by configuration alone.",
            action="Run check-in to send the first bounded activation receipt.",
        )

    def disable(self) -> dict[str, object]:
        policy = self.store.load(create=True)
        policy.update({"mode": "off", "prompted": True, "pending_event": None, "last_outcome": "DISABLED"})
        self.store.save(policy)
        return result(
            "DISABLED",
            policy,
            "Future analytics is disabled. This local action did not contact or erase the owner record.",
            action="Run erase if you also want the retained owner record deleted.",
        )

    def status(self) -> dict[str, object]:
        policy = self.store.load()
        return result(
            "STATUS",
            policy,
            f"Anonymous installation analytics is {policy['mode']}.",
            endpoint=policy["endpoint"],
            installation_id=policy["installation_id"],
            event_schema_version=SCHEMA_VERSION,
            last_sent_version=policy["last_sent_version"],
            last_event_id=policy["last_event_id"],
            last_success_at=policy["last_success_at"],
            last_outcome=policy["last_outcome"],
            pending=policy["pending_event"] is not None,
        )

    def _next_event(self, policy: Mapping[str, object]) -> dict[str, object] | None:
        pending = policy["pending_event"]
        if pending is not None:
            return validate_event(pending)
        version = package_version(self.skill_root)
        if policy["last_sent_version"] == version:
            return None
        event_type = "activated" if policy["last_sent_version"] is None else "version_changed"
        installation_id = policy["installation_id"]
        if not isinstance(installation_id, str):
            raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Enabled analytics has no installation ID.")
        return build_event(
            installation_id=installation_id,
            product_version=version,
            event_type=event_type,
            now=self.now_datetime,
        )

    def preview(self) -> dict[str, object]:
        policy = self.store.load()
        if policy["mode"] != "on":
            return result(
                "CONSENT_REQUIRED" if policy["mode"] == "unconfigured" else "ANALYTICS_DISABLED",
                policy,
                "No analytics event can be prepared until analytics is explicitly enabled.",
            )
        event = self._next_event(policy)
        return result(
            "NOT_DUE" if event is None else "EVENT_PREVIEW",
            policy,
            "This installation version was already recorded." if event is None else "Exact next analytics event; nothing was sent.",
            preview=event,
        )

    def check_in(self) -> dict[str, object]:
        policy = self.store.load()
        if policy["mode"] != "on":
            return result(
                "CONSENT_REQUIRED" if policy["mode"] == "unconfigured" else "ANALYTICS_DISABLED",
                policy,
                "Analytics check-in did not send because analytics is not enabled.",
            )
        event = self._next_event(policy)
        if event is None:
            return result("NOT_DUE", policy, "This installation version was already recorded.")
        policy["pending_event"] = event
        policy["last_outcome"] = "DELIVERY_PENDING"
        self.store.save(policy)
        endpoint = policy["endpoint"]
        if not isinstance(endpoint, str):
            raise AnalyticsError("ANALYTICS_POLICY_INVALID", "Enabled analytics has no endpoint.")
        try:
            receipt = self.transport_factory(endpoint).send(event)
        except AnalyticsError:
            policy["last_outcome"] = "DELIVERY_FAILED"
            self.store.save(policy)
            raise
        policy.update(
            {
                "last_sent_version": event["product_version"],
                "last_event_id": event["event_id"],
                "last_success_at": max(0, int(self.now_epoch())),
                "last_outcome": "EVENT_RECORDED",
                "pending_event": None,
            }
        )
        self.store.save(policy)
        return result(
            "EVENT_RECORDED",
            policy,
            "The bounded anonymous activation receipt was recorded.",
            event_id=event["event_id"],
            event_type=event["event_type"],
            product_version=event["product_version"],
            duplicate=receipt.get("status") == "duplicate",
        )

    def erase(self) -> dict[str, object]:
        policy = self.store.load()
        installation_id = policy["installation_id"]
        endpoint = policy["endpoint"]
        if not isinstance(installation_id, str) or not isinstance(endpoint, str):
            policy.update({"mode": "off", "prompted": True, "last_outcome": "NO_REMOTE_IDENTITY"})
            self.store.save(policy)
            return result("NO_REMOTE_IDENTITY", policy, "No configured remote analytics identity exists.")
        self.transport_factory(endpoint).erase(installation_id)
        policy.update(
            {
                "mode": "off",
                "prompted": True,
                "installation_id": None,
                "last_sent_version": None,
                "last_event_id": None,
                "last_success_at": None,
                "last_outcome": "REMOTE_ERASED",
                "pending_event": None,
            }
        )
        self.store.save(policy)
        return result("REMOTE_ERASED", policy, "The retained owner analytics record was deleted and local identity removed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage opt-in anonymous installation analytics.")
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-dir", type=Path, default=default_state_directory())
    parser.add_argument("--format", choices=("text", "json"), default="text")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prompt")
    enable = commands.add_parser("enable")
    enable.add_argument("--endpoint", default=os.environ.get(ENDPOINT_ENV), required=os.environ.get(ENDPOINT_ENV) is None)
    commands.add_parser("disable")
    commands.add_parser("status")
    commands.add_parser("preview")
    commands.add_parser("check-in")
    commands.add_parser("erase")
    return parser


def render_text(value: Mapping[str, object]) -> str:
    lines = [f"{value['status']}: {value['message']}"]
    if value.get("action"):
        lines.append(f"Action: {value['action']}")
    if value.get("preview"):
        lines.extend(["Preview:", json.dumps(value["preview"], indent=2, sort_keys=True, ensure_ascii=False)])
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = AnalyticsClient(args.skill_root, PolicyStore(args.state_dir))
    try:
        if args.command == "prompt":
            value = client.prompt()
        elif args.command == "enable":
            value = client.enable(args.endpoint)
        elif args.command == "disable":
            value = client.disable()
        elif args.command == "status":
            value = client.status()
        elif args.command == "preview":
            value = client.preview()
        elif args.command == "check-in":
            value = client.check_in()
        elif args.command == "erase":
            value = client.erase()
        else:
            parser.error("Unknown command")
            return 2
    except AnalyticsError as exc:
        policy = default_policy()
        with contextlib.suppress(AnalyticsError):
            policy = client.store.load()
        value = result(exc.code, policy, exc.message, action=exc.action)
        output = json.dumps(value, sort_keys=True, ensure_ascii=False) if args.format == "json" else render_text(value)
        print(output, file=sys.stderr)
        return 3
    output = json.dumps(value, sort_keys=True, ensure_ascii=False) if args.format == "json" else render_text(value)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

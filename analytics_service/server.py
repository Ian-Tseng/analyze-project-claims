#!/usr/bin/env python3
"""Private owner API for opt-in, privacy-bounded installation analytics."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import importlib.util
import json
import os
import re
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib import parse


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "skills" / "analyze-project-claims" / "scripts" / "installation_analytics.py"
SPEC = importlib.util.spec_from_file_location("analyze_project_claims_installation_analytics", CONTRACT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Installation-analytics contract could not be loaded.")
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


MAX_REQUEST_BYTES = 4 * 1024
CLIENT_HASHES_ENV = "ANALYTICS_API_TOKEN_HASHES"
ADMIN_HASH_ENV = "ANALYTICS_ADMIN_TOKEN_HASH"
IDENTITY_KEY_ENV = "ANALYTICS_ID_HASH_KEY"
TOKEN_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ApiError(RuntimeError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def parse_token_hashes(value: str | None) -> frozenset[str]:
    items = frozenset(item.strip().lower() for item in (value or "").split(",") if item.strip())
    if any(not TOKEN_HASH_PATTERN.fullmatch(item) for item in items):
        raise ValueError("Client token hashes must be comma-separated SHA-256 hex digests.")
    return items


@dataclass(frozen=True)
class Principal:
    digest: str
    admin: bool


class Authenticator:
    def __init__(self, client_hashes: frozenset[str], admin_hash: str) -> None:
        if not client_hashes:
            raise ValueError("At least one scoped analytics client token hash is required.")
        if not TOKEN_HASH_PATTERN.fullmatch(admin_hash):
            raise ValueError("Analytics admin token hash must be a SHA-256 hex digest.")
        self.client_hashes = client_hashes
        self.admin_hash = admin_hash

    def authenticate(self, header: str | None) -> Principal:
        if not isinstance(header, str) or not header.startswith("Bearer "):
            raise ApiError(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "A bearer token is required.")
        token = header[len("Bearer ") :]
        if not 20 <= len(token) <= 512 or re.search(r"\s", token):
            raise ApiError(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Bearer token is invalid.")
        digest = token_hash(token)
        if hmac.compare_digest(digest, self.admin_hash):
            return Principal(digest, True)
        if any(hmac.compare_digest(digest, allowed) for allowed in self.client_hashes):
            return Principal(digest, False)
        raise ApiError(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Bearer token is invalid.")


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int, *, clock: Callable[[], float] = time.monotonic) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("Rate limit and window must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self.clock()
        cutoff = now - self.window_seconds
        with self.lock:
            queue = self.events[key]
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if len(queue) >= self.limit:
                return False
            queue.append(now)
            return True


class AnalyticsStore:
    """Deduplicate installations while storing only keyed identity hashes."""

    def __init__(
        self,
        path: Path,
        identity_key: str,
        *,
        retention_seconds: int = 365 * 24 * 60 * 60,
    ) -> None:
        if retention_seconds < 1:
            raise ValueError("Analytics retention must be positive.")
        if not isinstance(identity_key, str) or len(identity_key) < 32:
            raise ValueError("Analytics identity hash key must contain at least 32 characters.")
        self.path = path.expanduser().absolute()
        self.identity_key = identity_key.encode("utf-8")
        self.retention_seconds = retention_seconds
        self._prepare_storage_path()
        self.lock = threading.Lock()
        self._initialize()
        self._harden_storage_files()
        self.purge(max(0, int(time.time()) - self.retention_seconds))

    def _storage_files(self) -> tuple[Path, ...]:
        return (
            self.path,
            Path(str(self.path) + "-wal"),
            Path(str(self.path) + "-shm"),
            Path(str(self.path) + "-journal"),
        )

    def _prepare_storage_path(self) -> None:
        for candidate in (*self._storage_files(), *self.path.parents):
            if candidate.is_symlink():
                raise ValueError(f"Analytics storage cannot traverse a symbolic link: {candidate}")
        if self.path.exists() and not self.path.is_file():
            raise ValueError("Analytics database path must be a regular file.")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink():
            raise ValueError("Analytics database directory cannot be a symbolic link.")
        if os.name != "nt":
            os.chmod(self.path.parent, 0o700)

    def _harden_storage_files(self) -> None:
        for candidate in self._storage_files():
            if candidate.is_symlink():
                raise ValueError(f"Analytics storage file cannot be a symbolic link: {candidate}")
            if os.name != "nt" and candidate.exists():
                os.chmod(candidate, 0o600)

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise ValueError("Analytics database path cannot be a symbolic link.")
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        self._harden_storage_files()
        return connection

    def _initialize(self) -> None:
        with contextlib.closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS installations (
                    installation_hash TEXT PRIMARY KEY,
                    principal_hash TEXT NOT NULL,
                    first_seen_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    current_version TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS installations_version
                    ON installations (current_version, last_seen_at DESC);
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    installation_hash TEXT NOT NULL,
                    principal_hash TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK (event_type IN ('activated','version_changed')),
                    product_version TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    received_at INTEGER NOT NULL,
                    FOREIGN KEY (installation_hash) REFERENCES installations(installation_hash)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS events_received ON events (received_at DESC);
                """
            )

    def identity_hash(self, installation_id: str) -> str:
        canonical = contract.canonical_uuid(installation_id, "installation_id")
        return hmac.new(self.identity_key, canonical.encode("ascii"), hashlib.sha256).hexdigest()

    def submit(self, principal_hash: str, event: Mapping[str, object], *, now: int | None = None) -> dict[str, object]:
        validated = contract.validate_event(dict(event))
        timestamp = max(0, int(time.time() if now is None else now))
        self.purge(timestamp - self.retention_seconds)
        installation_hash = self.identity_hash(str(validated["installation_id"]))
        with self.lock, contextlib.closing(self._connect()) as connection, connection:
            existing_event = connection.execute(
                "SELECT installation_hash, principal_hash FROM events WHERE event_id = ?",
                (validated["event_id"],),
            ).fetchone()
            if existing_event is not None:
                if (
                    existing_event["installation_hash"] != installation_hash
                    or existing_event["principal_hash"] != principal_hash
                ):
                    raise ApiError(HTTPStatus.CONFLICT, "EVENT_ID_CONFLICT", "Event ID is already bound.")
                return {"event_id": validated["event_id"], "status": "duplicate"}
            existing_installation = connection.execute(
                "SELECT principal_hash FROM installations WHERE installation_hash = ?", (installation_hash,)
            ).fetchone()
            if existing_installation is not None and existing_installation["principal_hash"] != principal_hash:
                raise ApiError(HTTPStatus.CONFLICT, "INSTALLATION_ID_CONFLICT", "Installation ID is already bound.")
            connection.execute(
                """
                INSERT INTO installations (
                    installation_hash, principal_hash, first_seen_at, last_seen_at, current_version
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(installation_hash) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    current_version = excluded.current_version
                """,
                (installation_hash, principal_hash, timestamp, timestamp, validated["product_version"]),
            )
            connection.execute(
                """
                INSERT INTO events (
                    event_id, installation_hash, principal_hash, event_type,
                    product_version, occurred_at, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    validated["event_id"],
                    installation_hash,
                    principal_hash,
                    validated["event_type"],
                    validated["product_version"],
                    validated["occurred_at"],
                    timestamp,
                ),
            )
        return {"event_id": validated["event_id"], "status": "recorded"}

    def erase(self, principal_hash: str, installation_id: str) -> dict[str, object]:
        installation_hash = self.identity_hash(installation_id)
        with self.lock, contextlib.closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM installations WHERE installation_hash = ? AND principal_hash = ?",
                (installation_hash, principal_hash),
            )
        return {"status": "deleted"}

    def summary(self) -> dict[str, object]:
        with contextlib.closing(self._connect()) as connection, connection:
            total = connection.execute("SELECT COUNT(*) FROM installations").fetchone()[0]
            events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            rows = connection.execute(
                """
                SELECT current_version, COUNT(*) AS installations
                FROM installations GROUP BY current_version ORDER BY current_version
                """
            ).fetchall()
        return {
            "metric": "unique_consenting_activated_installations",
            "unique_installations": total,
            "events": events,
            "by_version": [
                {"product_version": row["current_version"], "unique_installations": row["installations"]}
                for row in rows
            ],
        }

    def purge(self, before_timestamp: int) -> int:
        with self.lock, contextlib.closing(self._connect()) as connection, connection:
            return connection.execute("DELETE FROM installations WHERE last_seen_at < ?", (before_timestamp,)).rowcount


class AnalyticsHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        store: AnalyticsStore,
        auth: Authenticator,
        limiter: RateLimiter,
        auth_limiter: RateLimiter,
    ) -> None:
        super().__init__(address, AnalyticsHandler)
        self.store = store
        self.auth = auth
        self.limiter = limiter
        self.auth_limiter = auth_limiter


class AnalyticsHandler(BaseHTTPRequestHandler):
    server: AnalyticsHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, value: Mapping[str, object]) -> None:
        data = (json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, exc: ApiError) -> None:
        self._send(exc.status, {"error": exc.code, "message": exc.message})

    def _principal(self) -> Principal:
        peer = self.client_address[0] if self.client_address else "unknown"
        if not self.server.auth_limiter.allow(f"peer:{peer}"):
            raise ApiError(HTTPStatus.TOO_MANY_REQUESTS, "RATE_LIMITED", "Authentication rate limit exceeded.")
        return self.server.auth.authenticate(self.headers.get("Authorization"))

    def _json_body(self) -> dict[str, object]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json.")
        raw_length = self.headers.get("Content-Length")
        if not raw_length or not raw_length.isdigit():
            raise ApiError(HTTPStatus.LENGTH_REQUIRED, "LENGTH_REQUIRED", "A valid Content-Length is required.")
        length = int(raw_length)
        if length < 1 or length > MAX_REQUEST_BYTES:
            raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "REQUEST_TOO_LARGE", "Request body is too large.")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_JSON", "Request body must be strict UTF-8 JSON.") from exc
        if not isinstance(value, dict):
            raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_JSON", "Request body must be a JSON object.")
        return value

    def do_POST(self) -> None:
        try:
            principal = self._principal()
            if not self.server.limiter.allow(principal.digest):
                raise ApiError(HTTPStatus.TOO_MANY_REQUESTS, "RATE_LIMITED", "Analytics rate limit exceeded.")
            if self.path == "/v1/analytics/events":
                try:
                    event = contract.validate_event(self._json_body())
                except contract.AnalyticsError as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, exc.code, exc.message) from exc
                result = self.server.store.submit(principal.digest, event)
                self._send(HTTPStatus.OK if result["status"] == "duplicate" else HTTPStatus.CREATED, result)
                return
            if self.path == "/v1/analytics/erasures":
                value = self._json_body()
                if set(value) != {"installation_id"}:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "ANALYTICS_INVALID", "Erasure request has invalid fields.")
                try:
                    installation_id = contract.canonical_uuid(value["installation_id"], "installation_id")
                except contract.AnalyticsError as exc:
                    raise ApiError(HTTPStatus.BAD_REQUEST, exc.code, exc.message) from exc
                self._send(HTTPStatus.OK, self.server.store.erase(principal.digest, installation_id))
                return
            raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint was not found.")
        except ApiError as exc:
            self._error(exc)

    def do_GET(self) -> None:
        try:
            parsed = parse.urlparse(self.path)
            if parsed.path == "/healthz" and not parsed.query:
                self._send(HTTPStatus.OK, {"status": "ok"})
                return
            if parsed.path != "/v1/analytics/summary" or parsed.query:
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint was not found.")
            principal = self._principal()
            if not principal.admin:
                raise ApiError(HTTPStatus.FORBIDDEN, "FORBIDDEN", "Owner access is required.")
            self._send(HTTPStatus.OK, self.server.store.summary())
        except ApiError as exc:
            self._error(exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the private opt-in installation analytics API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument(
        "--database", type=Path, default=Path(".analytics-service-state/installation-analytics.sqlite3")
    )
    parser.add_argument("--rate-limit", type=int, default=20)
    parser.add_argument("--rate-window", type=int, default=3600)
    parser.add_argument("--auth-rate-limit", type=int, default=120)
    parser.add_argument("--auth-rate-window", type=int, default=3600)
    parser.add_argument("--retention-days", type=int, default=365)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.retention_days <= 3650:
        raise SystemExit("--retention-days must be between 1 and 3650")
    auth = Authenticator(
        parse_token_hashes(os.environ.get(CLIENT_HASHES_ENV)),
        (os.environ.get(ADMIN_HASH_ENV) or "").strip().lower(),
    )
    identity_key = os.environ.get(IDENTITY_KEY_ENV) or ""
    server = AnalyticsHTTPServer(
        (args.host, args.port),
        AnalyticsStore(
            args.database,
            identity_key,
            retention_seconds=args.retention_days * 24 * 60 * 60,
        ),
        auth,
        RateLimiter(args.rate_limit, args.rate_window),
        RateLimiter(args.auth_rate_limit, args.auth_rate_window),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

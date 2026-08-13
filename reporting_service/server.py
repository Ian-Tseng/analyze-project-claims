#!/usr/bin/env python3
"""Owner-side ingestion API for bounded analyze-project-claims reports."""

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
CONTRACT_PATH = ROOT / "skills" / "analyze-project-claims" / "scripts" / "problem_report.py"
SPEC = importlib.util.spec_from_file_location("analyze_project_claims_problem_report", CONTRACT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Problem-report contract could not be loaded.")
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)


MAX_REQUEST_BYTES = 16 * 1024
REPORT_STATUSES = {"received", "triaged", "fixed", "closed", "rejected"}
CLIENT_HASHES_ENV = "REPORT_API_TOKEN_HASHES"
ADMIN_HASH_ENV = "REPORT_ADMIN_TOKEN_HASH"
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
            raise ValueError("At least one scoped client token hash is required.")
        if not TOKEN_HASH_PATTERN.fullmatch(admin_hash):
            raise ValueError("Admin token hash must be a SHA-256 hex digest.")
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
        for allowed in self.client_hashes:
            if hmac.compare_digest(digest, allowed):
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


class ReportStore:
    def __init__(self, path: Path, *, retention_seconds: int = 90 * 24 * 60 * 60) -> None:
        if retention_seconds < 1:
            raise ValueError("Retention must be positive.")
        self.path = path.expanduser().absolute()
        self.retention_seconds = retention_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._initialize()
        self.purge(max(0, int(time.time()) - self.retention_seconds))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with contextlib.closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    principal_hash TEXT NOT NULL,
                    content_fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('received','triaged','fixed','closed','rejected')),
                    owner_note TEXT,
                    fixed_in_version TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE (principal_hash, content_fingerprint)
                );
                CREATE INDEX IF NOT EXISTS reports_status_updated
                    ON reports (status, updated_at DESC);
                """
            )

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, object]:
        payload = json.loads(row["payload_json"])
        return {
            "report_id": row["report_id"],
            "status": row["status"],
            "event_code": payload["event_code"],
            "component": payload["component"],
            "severity": payload["severity"],
            "product_version": payload["product_version"],
            "summary": payload["summary"],
            "content_fingerprint": row["content_fingerprint"],
            "owner_note": row["owner_note"],
            "fixed_in_version": row["fixed_in_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def submit(self, principal_hash: str, report: Mapping[str, object], *, now: int | None = None) -> dict[str, object]:
        validated = contract.validate_report(dict(report))
        timestamp = max(0, int(time.time() if now is None else now))
        self.purge(timestamp - self.retention_seconds)
        payload = json.dumps(validated, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self.lock, contextlib.closing(self._connect()) as connection, connection:
            existing = connection.execute(
                "SELECT * FROM reports WHERE principal_hash = ? AND content_fingerprint = ?",
                (principal_hash, validated["content_fingerprint"]),
            ).fetchone()
            if existing is not None:
                value = self._public(existing)
                value["duplicate"] = True
                value["submitted_report_id"] = validated["report_id"]
                return value
            connection.execute(
                """
                INSERT INTO reports (
                    report_id, principal_hash, content_fingerprint, payload_json,
                    status, owner_note, fixed_in_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'received', NULL, NULL, ?, ?)
                """,
                (
                    validated["report_id"],
                    principal_hash,
                    validated["content_fingerprint"],
                    payload,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute("SELECT * FROM reports WHERE report_id = ?", (validated["report_id"],)).fetchone()
        value = self._public(row)
        value["duplicate"] = False
        return value

    def get(self, report_id: str, principal: Principal) -> dict[str, object]:
        with contextlib.closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
        if row is None or (not principal.admin and row["principal_hash"] != principal.digest):
            raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Report was not found.")
        return self._public(row)

    def list(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, object]]:
        if status is not None and status not in REPORT_STATUSES:
            raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_STATUS", "Status filter is invalid.")
        limit = max(1, min(limit, 100))
        query = "SELECT * FROM reports"
        parameters: tuple[object, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            parameters = (status,)
        query += " ORDER BY updated_at DESC LIMIT ?"
        parameters += (limit,)
        with contextlib.closing(self._connect()) as connection, connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._public(row) for row in rows]

    def update(
        self,
        report_id: str,
        *,
        status: str,
        owner_note: str | None,
        fixed_in_version: str | None,
        now: int | None = None,
    ) -> dict[str, object]:
        if status not in REPORT_STATUSES:
            raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_STATUS", "Report status is invalid.")
        if owner_note is not None:
            owner_note = contract._safe_text(owner_note, "owner_note", minimum=1, maximum=500)
        if fixed_in_version is not None and not contract.SEMVER_PATTERN.fullmatch(fixed_in_version):
            raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_VERSION", "fixed_in_version must be SemVer.")
        if status == "fixed" and fixed_in_version is None:
            raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_VERSION", "Fixed reports require fixed_in_version.")
        timestamp = max(0, int(time.time() if now is None else now))
        with self.lock, contextlib.closing(self._connect()) as connection, connection:
            changed = connection.execute(
                """
                UPDATE reports
                SET status = ?, owner_note = ?, fixed_in_version = ?, updated_at = ?
                WHERE report_id = ?
                """,
                (status, owner_note, fixed_in_version, timestamp, report_id),
            ).rowcount
            if changed != 1:
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Report was not found.")
            row = connection.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
        return self._public(row)

    def delete(self, report_id: str, principal: Principal) -> dict[str, object]:
        with self.lock, contextlib.closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT principal_hash FROM reports WHERE report_id = ?", (report_id,)).fetchone()
            if row is None or (not principal.admin and row["principal_hash"] != principal.digest):
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Report was not found.")
            connection.execute("DELETE FROM reports WHERE report_id = ?", (report_id,))
        return {"report_id": report_id, "status": "deleted"}

    def purge(self, before_timestamp: int) -> int:
        with self.lock, contextlib.closing(self._connect()) as connection, connection:
            return connection.execute("DELETE FROM reports WHERE created_at < ?", (before_timestamp,)).rowcount


class ReportHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        store: ReportStore,
        auth: Authenticator,
        limiter: RateLimiter,
    ) -> None:
        super().__init__(address, ReportHandler)
        self.store = store
        self.auth = auth
        self.limiter = limiter


class ReportHandler(BaseHTTPRequestHandler):
    server: ReportHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, value: Mapping[str, object]) -> None:
        data = (json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
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
        return self.server.auth.authenticate(self.headers.get("Authorization"))

    def _json_body(self) -> dict[str, object]:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ApiError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json.")
        length_value = self.headers.get("Content-Length")
        if not length_value or not length_value.isdigit():
            raise ApiError(HTTPStatus.LENGTH_REQUIRED, "LENGTH_REQUIRED", "A valid Content-Length is required.")
        length = int(length_value)
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
            if self.path != "/v1/reports":
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint was not found.")
            principal = self._principal()
            if not self.server.limiter.allow(principal.digest):
                raise ApiError(HTTPStatus.TOO_MANY_REQUESTS, "RATE_LIMITED", "Report rate limit exceeded.")
            try:
                report = contract.validate_report(self._json_body())
            except contract.ReportError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, exc.code, exc.message) from exc
            result = self.server.store.submit(principal.digest, report)
            code = HTTPStatus.OK if result["duplicate"] else HTTPStatus.CREATED
            self._send(code, result)
        except ApiError as exc:
            self._error(exc)

    def do_GET(self) -> None:
        try:
            parsed = parse.urlparse(self.path)
            if parsed.path == "/healthz":
                self._send(HTTPStatus.OK, {"status": "ok"})
                return
            principal = self._principal()
            if parsed.path == "/v1/reports":
                if not principal.admin:
                    raise ApiError(HTTPStatus.FORBIDDEN, "FORBIDDEN", "Owner access is required.")
                query = parse.parse_qs(parsed.query, keep_blank_values=False)
                unexpected = set(query) - {"status", "limit"}
                if unexpected:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "Query contains unsupported fields.")
                status = query.get("status", [None])[0]
                raw_limit = query.get("limit", ["50"])[0]
                if not raw_limit.isdigit():
                    raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "limit must be an integer.")
                self._send(HTTPStatus.OK, {"reports": self.server.store.list(status=status, limit=int(raw_limit))})
                return
            match = re.fullmatch(r"/v1/reports/([0-9a-f-]{36})", parsed.path)
            if not match or parsed.query:
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint was not found.")
            try:
                report_id = contract._uuid(match.group(1), "report_id")
            except contract.ReportError as exc:
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Report was not found.") from exc
            self._send(HTTPStatus.OK, self.server.store.get(report_id, principal))
        except ApiError as exc:
            self._error(exc)

    def do_PATCH(self) -> None:
        try:
            parsed = parse.urlparse(self.path)
            match = re.fullmatch(r"/v1/reports/([0-9a-f-]{36})", parsed.path)
            if not match or parsed.query:
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint was not found.")
            principal = self._principal()
            if not principal.admin:
                raise ApiError(HTTPStatus.FORBIDDEN, "FORBIDDEN", "Owner access is required.")
            value = self._json_body()
            if set(value) != {"status", "owner_note", "fixed_in_version"}:
                raise ApiError(HTTPStatus.BAD_REQUEST, "INVALID_UPDATE", "Update has unknown or missing fields.")
            try:
                report_id = contract._uuid(match.group(1), "report_id")
                result = self.server.store.update(
                    report_id,
                    status=value["status"],
                    owner_note=value["owner_note"],
                    fixed_in_version=value["fixed_in_version"],
                )
            except contract.ReportError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, exc.code, exc.message) from exc
            self._send(HTTPStatus.OK, result)
        except ApiError as exc:
            self._error(exc)

    def do_DELETE(self) -> None:
        try:
            parsed = parse.urlparse(self.path)
            match = re.fullmatch(r"/v1/reports/([0-9a-f-]{36})", parsed.path)
            if not match or parsed.query:
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Endpoint was not found.")
            principal = self._principal()
            try:
                report_id = contract._uuid(match.group(1), "report_id")
            except contract.ReportError as exc:
                raise ApiError(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Report was not found.") from exc
            self._send(HTTPStatus.OK, self.server.store.delete(report_id, principal))
        except ApiError as exc:
            self._error(exc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the owner problem-report ingestion API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--database", type=Path, default=Path("problem-reports.sqlite3"))
    parser.add_argument("--rate-limit", type=int, default=20)
    parser.add_argument("--rate-window", type=int, default=3600)
    parser.add_argument("--retention-days", type=int, default=90)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.retention_days <= 3650:
        raise SystemExit("--retention-days must be between 1 and 3650")
    client_hashes = parse_token_hashes(os.environ.get(CLIENT_HASHES_ENV))
    admin_hash = (os.environ.get(ADMIN_HASH_ENV) or "").strip().lower()
    auth = Authenticator(client_hashes, admin_hash)
    server = ReportHTTPServer(
        (args.host, args.port),
        ReportStore(args.database, retention_seconds=args.retention_days * 24 * 60 * 60),
        auth,
        RateLimiter(args.rate_limit, args.rate_window),
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

from __future__ import annotations

import http.client
import importlib.util
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve()
CANDIDATE = HERE.parents[1]
ROOT = CANDIDATE if (CANDIDATE / "skills").is_dir() else CANDIDATE / "github" / "analyze-project-claims"
SERVER_PATH = ROOT / "analytics_service" / "server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("test_analytics_service_module", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AnalyticsServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = load_server()
        cls.client_token = "analytics-client-token-for-tests-123456"
        cls.other_token = "analytics-other-token-for-tests-12345"
        cls.admin_token = "analytics-admin-token-for-tests-1234567"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        auth = self.subject.Authenticator(
            frozenset(
                {
                    self.subject.token_hash(self.client_token),
                    self.subject.token_hash(self.other_token),
                }
            ),
            self.subject.token_hash(self.admin_token),
        )
        self.database = base / "analytics.sqlite3"
        self.server = self.subject.AnalyticsHTTPServer(
            ("127.0.0.1", 0),
            self.subject.AnalyticsStore(self.database, "identity-key-for-tests-with-32-plus-characters"),
            auth,
            self.subject.RateLimiter(20, 3600),
            self.subject.RateLimiter(120, 3600),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def event(self, **overrides):
        arguments = {
            "installation_id": "12345678-1234-4234-9234-123456789abc",
            "product_version": "0.7.0",
            "event_type": "activated",
            "now": lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
        }
        arguments.update(overrides)
        return self.subject.contract.build_event(**arguments)

    def request(self, method: str, path: str, *, token: str | None = None, value=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body = None
        if value is not None:
            body = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode("utf-8"))

    def test_health_public_but_events_and_summary_are_authenticated(self) -> None:
        self.assertEqual(self.request("GET", "/healthz"), (200, {"status": "ok"}))
        status, value = self.request("POST", "/v1/analytics/events", value=self.event())
        self.assertEqual((status, value["error"]), (401, "UNAUTHORIZED"))
        status, value = self.request("GET", "/v1/analytics/summary", token=self.client_token)
        self.assertEqual((status, value["error"]), (403, "FORBIDDEN"))

        self.server.auth_limiter = self.subject.RateLimiter(1, 3600)
        self.assertEqual(self.request("POST", "/v1/analytics/events", value=self.event())[0], 401)
        status, value = self.request("POST", "/v1/analytics/events", value=self.event())
        self.assertEqual((status, value["error"]), (429, "RATE_LIMITED"))

        self.server.auth_limiter = self.subject.RateLimiter(1, 3600)
        self.assertEqual(self.request("GET", "/v1/analytics/summary", token=self.admin_token)[0], 200)
        status, value = self.request("GET", "/v1/analytics/summary", token=self.admin_token)
        self.assertEqual((status, value["error"]), (429, "RATE_LIMITED"))

    def test_submit_deduplicates_and_owner_sees_only_aggregate(self) -> None:
        event = self.event()
        status, created = self.request("POST", "/v1/analytics/events", token=self.client_token, value=event)
        self.assertEqual((status, created["status"]), (201, "recorded"))
        status, duplicate = self.request("POST", "/v1/analytics/events", token=self.client_token, value=event)
        self.assertEqual((status, duplicate["status"]), (200, "duplicate"))
        status, summary = self.request("GET", "/v1/analytics/summary", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(summary["metric"], "unique_consenting_activated_installations")
        self.assertEqual(summary["unique_installations"], 1)
        self.assertEqual(summary["events"], 1)
        self.assertEqual(summary["by_version"], [{"product_version": "0.7.0", "unique_installations": 1}])
        self.assertNotIn("installation", json.dumps(summary["by_version"][0]).replace("installations", ""))

    def test_production_transport_round_trip(self) -> None:
        endpoint = f"http://127.0.0.1:{self.server.server_port}/v1/analytics/events"
        transport = self.subject.contract.ApiTransport(endpoint, token=self.client_token)
        event = self.event()
        self.assertEqual(transport.send(event), {"event_id": event["event_id"], "status": "recorded"})
        self.assertEqual(transport.erase(event["installation_id"]), {"status": "deleted"})
        self.assertEqual(self.server.store.summary()["unique_installations"], 0)

    def test_raw_installation_id_is_never_stored(self) -> None:
        event = self.event()
        self.request("POST", "/v1/analytics/events", token=self.client_token, value=event)
        raw = self.database.read_bytes()
        self.assertNotIn(event["installation_id"].encode("ascii"), raw)
        self.assertIn(self.server.store.identity_hash(event["installation_id"]).encode("ascii"), raw)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.database.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(self.database.stat().st_mode), 0o600)
            target = Path(self.temporary.name) / "target"
            target.mkdir()
            link = Path(self.temporary.name) / "linked-state"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                self.subject.AnalyticsStore(link / "analytics.sqlite3", "another-identity-key-with-32-characters")

            sidecar_root = Path(self.temporary.name) / "sidecar-state"
            sidecar_root.mkdir()
            sidecar_target = Path(self.temporary.name) / "sidecar-target.txt"
            sidecar_target.write_text("unchanged", encoding="utf-8")
            database = sidecar_root / "analytics.sqlite3"
            Path(str(database) + "-wal").symlink_to(sidecar_target)
            with self.assertRaises(ValueError):
                self.subject.AnalyticsStore(database, "sidecar-identity-key-with-32-characters")
            self.assertEqual(sidecar_target.read_text(encoding="utf-8"), "unchanged")

    def test_erasure_is_principal_scoped_and_idempotent(self) -> None:
        event = self.event()
        self.request("POST", "/v1/analytics/events", token=self.client_token, value=event)
        erasure = {"installation_id": event["installation_id"]}
        self.request("POST", "/v1/analytics/erasures", token=self.other_token, value=erasure)
        self.assertEqual(self.server.store.summary()["unique_installations"], 1)
        status, value = self.request("POST", "/v1/analytics/erasures", token=self.client_token, value=erasure)
        self.assertEqual((status, value), (200, {"status": "deleted"}))
        self.assertEqual(self.server.store.summary()["unique_installations"], 0)
        self.assertEqual(self.server.store.summary()["events"], 0)

    def test_schema_rejects_unknown_fields_and_retention_purges_inactive_installations(self) -> None:
        event = self.event()
        event["username"] = "not allowed"
        status, value = self.request("POST", "/v1/analytics/events", token=self.client_token, value=event)
        self.assertEqual((status, value["error"]), (400, "ANALYTICS_INVALID"))

        old = self.event()
        principal = self.subject.token_hash(self.client_token)
        self.server.store.submit(principal, old, now=100)
        fresh = self.event(installation_id="87654321-4321-4321-8321-cba987654321")
        self.server.store.submit(principal, fresh, now=100 + self.server.store.retention_seconds + 1)
        self.assertEqual(self.server.store.summary()["unique_installations"], 1)


if __name__ == "__main__":
    unittest.main()

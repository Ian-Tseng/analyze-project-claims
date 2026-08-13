from __future__ import annotations

import http.client
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve()
CANDIDATE = HERE.parents[1]
ROOT = CANDIDATE if (CANDIDATE / "skills").is_dir() else CANDIDATE / "github" / "analyze-project-claims"
SERVER_PATH = ROOT / "reporting_service" / "server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("test_reporting_service_module", SERVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReportingServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = load_server()
        cls.client_token = "client-token-for-tests-1234567890"
        cls.other_token = "other-client-token-tests-123456789"
        cls.admin_token = "admin-token-for-tests-12345678900"

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        skill = base / "skill"
        (skill / "references").mkdir(parents=True)
        (skill / "references" / "package-version.json").write_text(
            json.dumps({"schema_version": 1, "skill_name": "analyze-project-claims", "version": "0.5.0"}),
            encoding="utf-8",
        )
        self.skill = skill
        auth = self.subject.Authenticator(
            frozenset(
                {
                    self.subject.token_hash(self.client_token),
                    self.subject.token_hash(self.other_token),
                }
            ),
            self.subject.token_hash(self.admin_token),
        )
        self.server = self.subject.ReportHTTPServer(
            ("127.0.0.1", 0),
            self.subject.ReportStore(base / "reports.sqlite3"),
            auth,
            self.subject.RateLimiter(20, 3600),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def report(self, **overrides):
        arguments = {
            "skill_root": self.skill,
            "installation_id": "12345678-1234-4234-9234-123456789abc",
            "event_code": "UPDATE_INTEGRITY_FAILURE",
            "summary": "Installed package failed the post-update integrity check.",
            "reproduction_steps": ["Run consented update maintenance", "Verify the installed package"],
            "outcome_code": "INVALID_POSTCONDITION",
            "exit_code": 3,
            "now": lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
            "gh_command": ("definitely-not-installed-gh",),
        }
        arguments.update(overrides)
        return self.subject.contract.build_report(**arguments)

    def request(self, method: str, path: str, *, token: str | None = None, value=None, content_type="application/json"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        headers = {"Accept": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body = None
        if value is not None:
            body = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = content_type
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw.decode("utf-8"))

    def test_health_is_public_but_reports_require_authentication(self) -> None:
        status, value = self.request("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(value, {"status": "ok"})
        status, value = self.request("POST", "/v1/reports", value=self.report())
        self.assertEqual(status, 401)
        self.assertEqual(value["error"], "UNAUTHORIZED")

    def test_submit_deduplicate_status_and_owner_resolution(self) -> None:
        report = self.report()
        status, created = self.request("POST", "/v1/reports", token=self.client_token, value=report)
        self.assertEqual(status, 201)
        self.assertFalse(created["duplicate"])
        self.assertEqual(created["report_id"], report["report_id"])

        duplicate_report = self.report()
        status, duplicate = self.request("POST", "/v1/reports", token=self.client_token, value=duplicate_report)
        self.assertEqual(status, 200)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["report_id"], report["report_id"])
        self.assertEqual(duplicate["submitted_report_id"], duplicate_report["report_id"])

        status, visible = self.request("GET", f"/v1/reports/{report['report_id']}", token=self.client_token)
        self.assertEqual(status, 200)
        self.assertEqual(visible["status"], "received")
        status, hidden = self.request("GET", f"/v1/reports/{report['report_id']}", token=self.other_token)
        self.assertEqual(status, 404)
        self.assertEqual(hidden["error"], "NOT_FOUND")

        update = {"status": "fixed", "owner_note": "Resolved in the managed reporter.", "fixed_in_version": "0.5.1"}
        status, fixed = self.request(
            "PATCH", f"/v1/reports/{report['report_id']}", token=self.admin_token, value=update
        )
        self.assertEqual(status, 200)
        self.assertEqual(fixed["status"], "fixed")
        self.assertEqual(fixed["fixed_in_version"], "0.5.1")

        status, listing = self.request("GET", "/v1/reports?status=fixed", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual([item["report_id"] for item in listing["reports"]], [report["report_id"]])

    def test_server_revalidates_content_type_schema_and_redaction(self) -> None:
        report = self.report()
        status, value = self.request(
            "POST", "/v1/reports", token=self.client_token, value=report, content_type="text/plain"
        )
        self.assertEqual(status, 415)
        self.assertEqual(value["error"], "UNSUPPORTED_MEDIA_TYPE")

        report["raw_log"] = "not allowed"
        status, value = self.request("POST", "/v1/reports", token=self.client_token, value=report)
        self.assertEqual(status, 400)
        self.assertEqual(value["error"], "REPORT_INVALID")

        report = self.report()
        # Client construction rejects this before transmission; simulate a hostile client by
        # starting from a valid report and recomputing the fingerprint manually.
        report["summary"] = "Failure exposed token ghp_abcdefghijklmnopqrstuvwxyz123456"
        report["content_fingerprint"] = self.subject.contract.report_fingerprint(report)
        status, value = self.request("POST", "/v1/reports", token=self.client_token, value=report)
        self.assertEqual(status, 400)
        self.assertEqual(value["error"], "REPORT_REDACTION_REQUIRED")

    def test_rate_limit_is_per_authenticated_principal(self) -> None:
        self.server.limiter = self.subject.RateLimiter(1, 3600)
        first = self.report()
        status, _ = self.request("POST", "/v1/reports", token=self.client_token, value=first)
        self.assertEqual(status, 201)
        status, value = self.request("POST", "/v1/reports", token=self.client_token, value=self.report())
        self.assertEqual(status, 429)
        self.assertEqual(value["error"], "RATE_LIMITED")
        status, _ = self.request("POST", "/v1/reports", token=self.other_token, value=self.report())
        self.assertEqual(status, 201)

    def test_fixed_status_requires_semver_and_owner_access(self) -> None:
        report = self.report()
        self.request("POST", "/v1/reports", token=self.client_token, value=report)
        invalid = {"status": "fixed", "owner_note": None, "fixed_in_version": None}
        status, value = self.request(
            "PATCH", f"/v1/reports/{report['report_id']}", token=self.admin_token, value=invalid
        )
        self.assertEqual(status, 400)
        self.assertEqual(value["error"], "INVALID_VERSION")
        status, value = self.request(
            "PATCH", f"/v1/reports/{report['report_id']}", token=self.client_token, value=invalid
        )
        self.assertEqual(status, 403)
        self.assertEqual(value["error"], "FORBIDDEN")

    def test_client_can_delete_only_its_own_report(self) -> None:
        report = self.report()
        self.request("POST", "/v1/reports", token=self.client_token, value=report)
        status, hidden = self.request("DELETE", f"/v1/reports/{report['report_id']}", token=self.other_token)
        self.assertEqual(status, 404)
        self.assertEqual(hidden["error"], "NOT_FOUND")
        status, deleted = self.request("DELETE", f"/v1/reports/{report['report_id']}", token=self.client_token)
        self.assertEqual(status, 200)
        self.assertEqual(deleted, {"report_id": report["report_id"], "status": "deleted"})
        status, missing = self.request("GET", f"/v1/reports/{report['report_id']}", token=self.client_token)
        self.assertEqual(status, 404)
        self.assertEqual(missing["error"], "NOT_FOUND")

    def test_retention_purges_expired_reports(self) -> None:
        store = self.server.store
        principal = self.subject.Principal(self.subject.token_hash(self.client_token), False)
        old = self.report(summary="An old bounded report ready for retention cleanup.")
        store.submit(principal.digest, old, now=100)
        fresh = self.report(summary="A fresh bounded report retained by the service.")
        store.submit(principal.digest, fresh, now=100 + store.retention_seconds + 1)
        with self.assertRaises(self.subject.ApiError) as raised:
            store.get(old["report_id"], principal)
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(store.get(fresh["report_id"], principal)["report_id"], fresh["report_id"])

    def test_startup_purges_reports_older_than_retention(self) -> None:
        store = self.server.store
        principal = self.subject.Principal(self.subject.token_hash(self.client_token), False)
        old = self.report(summary="An expired bounded report present before service restart.")
        store.submit(principal.digest, old, now=1)
        restarted = self.subject.ReportStore(store.path, retention_seconds=store.retention_seconds)
        with self.assertRaises(self.subject.ApiError) as raised:
            restarted.get(old["report_id"], principal)
        self.assertEqual(raised.exception.status, 404)


if __name__ == "__main__":
    unittest.main()

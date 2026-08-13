from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve()
CANDIDATE = HERE.parents[1]
ROOT = CANDIDATE if (CANDIDATE / "skills").is_dir() else CANDIDATE / "github" / "analyze-project-claims"
MODULE_PATH = ROOT / "skills" / "analyze-project-claims" / "scripts" / "problem_report.py"


def load_module():
    spec = importlib.util.spec_from_file_location("test_problem_report_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, module) -> None:
        self.module = module
        self.reports: list[dict[str, object]] = []

    def send(self, report):
        self.reports.append(dict(report))
        return self.module.DeliveryResult(str(report["report_id"]), "received", "https://example.test/report")

    def status(self, report_id):
        return self.module.DeliveryResult(report_id, "triaged", f"https://example.test/{report_id}")

    def delete(self, report_id):
        return self.module.DeliveryResult(report_id, "deleted", None)


class FakeRunner:
    def __init__(self, module, repository: str) -> None:
        self.module = module
        self.repository = repository
        self.calls: list[list[str]] = []
        self.body = ""

    def run(self, arguments, *, timeout):
        self.calls.append(list(arguments))
        body_path = Path(arguments[arguments.index("--body-file") + 1])
        self.body = body_path.read_text(encoding="utf-8")
        return self.module.NativeResult(0, f"https://github.com/{self.repository}/issues/17\n", "")


class ProblemReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = load_module()

    def make_skill(self, base: Path, version: str = "0.5.0") -> Path:
        root = base / "skill"
        (root / "references").mkdir(parents=True)
        (root / "references" / "package-version.json").write_text(
            json.dumps({"schema_version": 1, "skill_name": "analyze-project-claims", "version": version}),
            encoding="utf-8",
        )
        return root

    def build_report(self, root: Path, installation_id: str | None = None, **overrides):
        arguments = {
            "skill_root": root,
            "installation_id": installation_id or "12345678-1234-4234-9234-123456789abc",
            "event_code": "UPDATE_NATIVE_FAILURE",
            "summary": "The native update command returned a transient failure.",
            "reproduction_steps": ["Complete the skill task", "Run bounded update maintenance"],
            "outcome_code": "TRANSIENT_FAILURE",
            "exit_code": 1,
            "now": lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
            "gh_command": ("definitely-not-installed-gh",),
        }
        arguments.update(overrides)
        return self.subject.build_report(**arguments)

    def test_prepare_is_local_and_requires_consent_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_skill(base)
            transport = FakeTransport(self.subject)
            reporter = self.subject.Reporter(
                root,
                self.subject.PolicyStore(base / "state"),
                gh_command=("definitely-not-installed-gh",),
                github_factory=lambda _repository: transport,
            )
            prepared = reporter.prepare(
                event_code="UPDATE_NATIVE_FAILURE",
                summary="The native update command returned a transient failure.",
                reproduction_steps=["Complete the skill task", "Run bounded update maintenance"],
                outcome_code="TRANSIENT_FAILURE",
                exit_code=1,
            )
            self.assertEqual(prepared["status"], "REPORT_PREPARED")
            self.assertTrue(prepared["consent_required"])
            self.assertEqual(transport.reports, [])
            report_path = Path(prepared["report_path"])
            report = self.subject.load_report(report_path)
            self.assertEqual(set(report), self.subject.REPORT_KEYS)
            self.assertNotIn("prompt", json.dumps(report).lower())
            self.assertNotIn("attachment", json.dumps(report).lower())

            refused = reporter.submit(report_path)
            self.assertEqual(refused["status"], "CONSENT_REQUIRED")
            self.assertEqual(transport.reports, [])

            sent = reporter.submit(report_path, approved=True)
            self.assertEqual(sent["status"], "REPORT_SENT")
            self.assertEqual(len(transport.reports), 1)

    def test_auto_minimal_uses_only_fixed_internal_event_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_skill(base)
            transport = FakeTransport(self.subject)
            reporter = self.subject.Reporter(
                root,
                self.subject.PolicyStore(base / "state"),
                gh_command=("definitely-not-installed-gh",),
                github_factory=lambda _repository: transport,
            )
            reporter.configure("auto-minimal", transport="github")
            prepared = reporter.prepare(
                event_code="COMPONENT_MAP_INTERNAL_ERROR",
                summary="Component map helper exited before producing a candidate.",
            )
            sent = reporter.submit(Path(prepared["report_path"]))
            self.assertEqual(sent["status"], "REPORT_SENT")
            self.assertEqual(transport.reports[0]["component"], "component-map")

            with self.assertRaises(self.subject.ReportError):
                reporter.prepare(event_code="USER_PROJECT_FINDING", summary="A user project has a defect.")

    def test_api_status_and_deletion_are_installation_scoped_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_skill(base)
            transport = FakeTransport(self.subject)
            reporter = self.subject.Reporter(
                root,
                self.subject.PolicyStore(base / "state"),
                api_factory=lambda _endpoint: transport,
            )
            reporter.configure("ask", transport="api", endpoint="http://127.0.0.1:8080/v1/reports")
            report_id = "12345678-1234-4234-9234-123456789abc"
            self.assertEqual(reporter.remote_status(report_id)["remote_status"], "triaged")
            self.assertEqual(reporter.remote_delete(report_id)["remote_status"], "deleted")

    def test_redaction_rejects_credentials_paths_and_control_characters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_skill(Path(temporary))
            bad = (
                "GitHub token ghp_abcdefghijklmnopqrstuvwxyz123456",
                "Failure occurred at C:\\Users\\person\\secret.txt",
                "Failure occurred at /home/person/private/file.txt",
                "Failure contains a newline\nand hidden text",
            )
            for summary in bad:
                with self.subTest(summary=summary), self.assertRaises(self.subject.ReportError) as raised:
                    self.build_report(root, summary=summary)
                self.assertEqual(raised.exception.code, "REPORT_REDACTION_REQUIRED")

    def test_tampering_and_unknown_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_skill(Path(temporary))
            report = self.build_report(root)
            report["summary"] = "A different summary that should not match the fingerprint."
            with self.assertRaises(self.subject.ReportError) as raised:
                self.subject.validate_report(report)
            self.assertEqual(raised.exception.code, "REPORT_INVALID")
            report = self.build_report(root)
            report["raw_log"] = "not allowed"
            with self.assertRaises(self.subject.ReportError):
                self.subject.validate_report(report)

    def test_github_transport_uses_argument_array_and_bounded_body_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = self.make_skill(Path(temporary))
            report = self.build_report(root)
            runner = FakeRunner(self.subject, "owner/repository")
            transport = self.subject.GitHubTransport("owner/repository", runner=runner)
            result = transport.send(report)
            self.assertEqual(result.remote_id, "17")
            call = runner.calls[0]
            self.assertEqual(call[:5], ["gh", "issue", "create", "--repo", "owner/repository"])
            self.assertIn("--body-file", call)
            self.assertNotIn("--label", call)
            self.assertIn("Internal product report", runner.body)
            self.assertNotIn(str(Path.home()), runner.body)

    def test_policy_schema_is_exact_and_never_stores_api_token(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = self.subject.PolicyStore(Path(temporary))
            state = store.load(create=True)
            self.assertEqual(set(state), self.subject.POLICY_KEYS)
            state["api_token"] = "not allowed"
            with self.assertRaises(self.subject.ReportError):
                self.subject.validate_policy(state)
            raw = store.path.read_text(encoding="utf-8").lower()
            self.assertNotIn("token", raw)

    def test_repository_schemas_match_runtime_keys_and_enums(self) -> None:
        report_schema = json.loads(
            (ROOT / "skills" / "analyze-project-claims" / "references" / "problem-report.schema.json").read_text(
                encoding="utf-8"
            )
        )
        policy_schema = json.loads(
            (
                ROOT
                / "skills"
                / "analyze-project-claims"
                / "references"
                / "problem-report-policy.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(report_schema["additionalProperties"])
        self.assertEqual(set(report_schema["required"]), self.subject.REPORT_KEYS)
        self.assertEqual(set(report_schema["properties"]["event_code"]["enum"]), set(self.subject.EVENTS))
        self.assertFalse(policy_schema["additionalProperties"])
        self.assertEqual(set(policy_schema["required"]), self.subject.POLICY_KEYS)


if __name__ == "__main__":
    unittest.main()

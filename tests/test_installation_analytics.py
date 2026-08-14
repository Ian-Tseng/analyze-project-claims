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
MODULE_PATH = ROOT / "skills" / "analyze-project-claims" / "scripts" / "installation_analytics.py"


def load_module():
    spec = importlib.util.spec_from_file_location("test_installation_analytics_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeTransport:
    def __init__(self, module, *, fail: bool = False) -> None:
        self.module = module
        self.fail = fail
        self.events: list[dict[str, object]] = []
        self.erasures: list[str] = []

    def send(self, event):
        self.events.append(dict(event))
        if self.fail:
            raise self.module.AnalyticsError("ANALYTICS_DELIVERY_FAILED", "Owner API is unavailable.")
        return {"event_id": event["event_id"], "status": "recorded"}

    def erase(self, installation_id):
        self.erasures.append(installation_id)
        return {"status": "deleted"}


class InstallationAnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = load_module()

    def make_skill(self, base: Path, version: str = "0.7.0") -> Path:
        root = base / "skill"
        (root / "references").mkdir(parents=True)
        (root / "references" / "package-version.json").write_text(
            json.dumps({"schema_version": 1, "skill_name": "analyze-project-claims", "version": version}),
            encoding="utf-8",
        )
        return root

    def make_client(self, base: Path, transport: FakeTransport):
        root = self.make_skill(base)
        client = self.subject.AnalyticsClient(
            root,
            self.subject.PolicyStore(base / "state"),
            transport_factory=lambda _endpoint: transport,
            now_datetime=lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
            now_epoch=lambda: 1_786_579_200,
        )
        return root, client

    def test_default_and_prompt_never_send_or_create_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            transport = FakeTransport(self.subject)
            _root, client = self.make_client(base, transport)
            first = client.prompt()
            second = client.prompt()
            self.assertEqual(first["status"], "CONSENT_REQUIRED")
            self.assertEqual(second["status"], "NO_PROMPT")
            policy = client.store.load()
            self.assertIsNone(policy["installation_id"])
            self.assertEqual(transport.events, [])

    def test_enable_sends_nothing_then_check_in_records_once_per_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            transport = FakeTransport(self.subject)
            root, client = self.make_client(base, transport)
            enabled = client.enable("http://127.0.0.1:8081/v1/analytics/events")
            self.assertEqual(enabled["status"], "ENABLED")
            self.assertEqual(transport.events, [])
            preview = client.preview()
            self.assertEqual(preview["preview"]["event_type"], "activated")
            self.assertEqual(set(preview["preview"]), self.subject.EVENT_KEYS)

            sent = client.check_in()
            self.assertEqual(sent["status"], "EVENT_RECORDED")
            self.assertEqual(sent["event_type"], "activated")
            self.assertEqual(client.check_in()["status"], "NOT_DUE")
            self.assertEqual(len(transport.events), 1)

            (root / "references" / "package-version.json").write_text(
                json.dumps({"schema_version": 1, "skill_name": "analyze-project-claims", "version": "0.7.1"}),
                encoding="utf-8",
            )
            changed = client.check_in()
            self.assertEqual(changed["event_type"], "version_changed")
            self.assertEqual(changed["product_version"], "0.7.1")
            self.assertEqual(len(transport.events), 2)

    def test_failed_delivery_retries_same_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            transport = FakeTransport(self.subject, fail=True)
            _root, client = self.make_client(base, transport)
            client.enable("http://127.0.0.1:8081/v1/analytics/events")
            with self.assertRaises(self.subject.AnalyticsError):
                client.check_in()
            pending_id = client.store.load()["pending_event"]["event_id"]
            transport.fail = False
            client.check_in()
            self.assertEqual([event["event_id"] for event in transport.events], [pending_id, pending_id])

    def test_disable_is_local_and_erase_removes_remote_and_local_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            transport = FakeTransport(self.subject)
            _root, client = self.make_client(base, transport)
            client.enable("http://127.0.0.1:8081/v1/analytics/events")
            installation_id = client.store.load()["installation_id"]
            disabled = client.disable()
            self.assertEqual(disabled["status"], "DISABLED")
            self.assertEqual(transport.erasures, [])
            erased = client.erase()
            self.assertEqual(erased["status"], "REMOTE_ERASED")
            self.assertEqual(transport.erasures, [installation_id])
            self.assertIsNone(client.store.load()["installation_id"])

    def test_policy_and_event_schemas_are_exact_and_token_is_never_stored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            transport = FakeTransport(self.subject)
            _root, client = self.make_client(base, transport)
            client.enable("http://127.0.0.1:8081/v1/analytics/events")
            raw = client.store.path.read_text(encoding="utf-8").lower()
            self.assertNotIn("token", raw)
            event_schema = json.loads(
                (ROOT / "skills" / "analyze-project-claims" / "references" / "installation-analytics-event.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            policy_schema = json.loads(
                (ROOT / "skills" / "analyze-project-claims" / "references" / "installation-analytics-policy.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(event_schema["additionalProperties"])
            self.assertEqual(set(event_schema["required"]), self.subject.EVENT_KEYS)
            self.assertFalse(policy_schema["additionalProperties"])
            self.assertEqual(set(policy_schema["required"]), self.subject.POLICY_KEYS)

    def test_public_docs_bound_the_metric_and_keep_consent_separate(self) -> None:
        guide = (ROOT / "docs" / "INSTALLATION_ANALYTICS.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        skill = (ROOT / "skills" / "analyze-project-claims" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("unique consenting activated installations", guide)
        self.assertIn("does not measure GitHub downloads", guide)
        self.assertIn("No analytics endpoint is bundled", guide)
        self.assertIn("does not send analytics by default", readme)
        self.assertIn("Update consent and reporting consent do not authorize", skill)
        self.assertIn("never downloads, users, or total installs", skill)


if __name__ == "__main__":
    unittest.main()

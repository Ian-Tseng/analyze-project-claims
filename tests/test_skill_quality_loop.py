import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "analyze-project-claims"
SCRIPTS = SKILL_ROOT / "scripts"
CLI = SCRIPTS / "skill_quality_loop.py"
sys.path.insert(0, str(SCRIPTS))

from _internal.skill_quality import contract  # noqa: E402
from _internal.skill_quality import store as store_module  # noqa: E402
from _internal.skill_quality.store import QualityStore  # noqa: E402


class SkillOutcomeReceiptTests(unittest.TestCase):
    def receipt(self, **overrides):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        values = {
            "owner": "Ian-Tseng",
            "repository": "example-producer",
            "skill": "example-producer",
            "version": "1.2.3",
            "package_digest_sha256": "a" * 64,
            "outcome": "completed_with_limitations",
            "quality_signal": "claim_evidence_gap",
            "requested_action": "analyze_quality",
            "created_at": now,
            "expires_at": now + timedelta(hours=1),
        }
        values.update(overrides)
        return contract.create_receipt(**values)

    def test_marker_round_trip_is_closed_and_content_free(self) -> None:
        receipt = self.receipt()
        marker = contract.format_marker(receipt)
        parsed = contract.extract_trailing_marker("Producer result\n\n" + marker)
        self.assertEqual(parsed, receipt)
        self.assertNotIn("Producer result", json.dumps(receipt))
        self.assertLessEqual(len(marker.encode("utf-8")), contract.MAX_MARKER_BYTES)

    def test_unknown_or_content_bearing_fields_are_rejected(self) -> None:
        receipt = self.receipt()
        receipt["summary"] = "C:/private/project secret"
        with self.assertRaisesRegex(contract.QualityError, "RECEIPT_SCHEMA_VIOLATION"):
            contract.validate_receipt(receipt)

    def test_expired_receipt_is_rejected(self) -> None:
        created = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
        receipt = self.receipt(
            created_at=created,
            expires_at=created + timedelta(hours=1),
        )
        with self.assertRaisesRegex(contract.QualityError, "RECEIPT_EXPIRED"):
            contract.validate_receipt(
                receipt,
                now=datetime(2026, 8, 20, 2, 0, tzinfo=timezone.utc),
            )

    def test_future_dated_receipt_is_rejected(self) -> None:
        current = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
        receipt = self.receipt(
            created_at=current + timedelta(hours=1),
            expires_at=current + timedelta(hours=2),
        )
        with self.assertRaisesRegex(contract.QualityError, "RECEIPT_FUTURE_DATED"):
            contract.validate_receipt(receipt, now=current)

    def test_no_issue_requires_no_action(self) -> None:
        receipt = self.receipt(quality_signal="no_issue", requested_action="none")
        receipt["requested_action"] = "analyze_quality"
        receipt["receipt_digest_sha256"] = contract.receipt_digest(receipt)
        with self.assertRaisesRegex(contract.QualityError, "RECEIPT_SCHEMA_VIOLATION"):
            contract.validate_receipt(receipt)


class QualityStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="skill-quality-")
        self.state_dir = Path(self.temp.name)
        self.store = QualityStore(self.state_dir)
        now = datetime.now(timezone.utc)
        self.receipt = contract.create_receipt(
            owner="Ian-Tseng",
            repository="example-producer",
            skill="example-producer",
            version="1.2.3",
            package_digest_sha256="b" * 64,
            outcome="completed_with_limitations",
            quality_signal="lifecycle_inconsistency",
            requested_action="analyze_quality",
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_replay_commits_one_proposal(self) -> None:
        first = self.store.consume(self.receipt, analyzer_version="1.0.0")
        second = self.store.consume(self.receipt, analyzer_version="1.0.0")
        self.assertEqual(first["proposal_id"], second["proposal_id"])
        self.assertTrue(second["deduplicated"])
        status = self.store.status()
        self.assertEqual(status["proposal_count"], 1)
        self.assertEqual(status["outbound_actions"], 0)

    def test_concurrent_replay_commits_one_proposal(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(
                workers.map(
                    lambda _: self.store.consume(self.receipt, analyzer_version="1.0.0"),
                    range(16),
                )
            )
        self.assertEqual(len({result["proposal_id"] for result in results}), 1)
        self.assertEqual(self.store.status()["proposal_count"], 1)

    def test_expired_claim_lease_is_recoverable(self) -> None:
        digest = self.receipt["receipt_digest_sha256"]
        self.store.receive(self.receipt)
        claimed = self.store.claim(digest, lease_seconds=1)
        self.assertEqual(claimed["state"], "CLAIMED")
        recovered = self.store.claim(
            digest,
            lease_seconds=1,
            now=datetime.now(timezone.utc) + timedelta(seconds=2),
        )
        self.assertEqual(recovered["state"], "CLAIMED")
        self.assertNotEqual(claimed["lease_id"], recovered["lease_id"])

    def test_active_claim_blocks_other_consumer_but_owner_can_commit(self) -> None:
        digest = self.receipt["receipt_digest_sha256"]
        self.store.receive(self.receipt)
        claimed = self.store.claim(digest, lease_seconds=30)
        with self.assertRaisesRegex(contract.QualityError, "RECEIPT_BUSY"):
            self.store.consume_next(analyzer_version="1.0.0")
        proposal = self.store.consume(
            self.receipt,
            analyzer_version="1.0.0",
            lease_id=claimed["lease_id"],
        )
        self.assertEqual(proposal["status"], "active")

    def test_expired_oldest_receipt_is_pruned_before_fresh_consume(self) -> None:
        current = datetime.now(timezone.utc).replace(microsecond=0)
        expired = contract.create_receipt(
            owner="Ian-Tseng",
            repository="expired",
            skill="expired",
            version="1.0.0",
            package_digest_sha256="d" * 64,
            outcome="failed",
            quality_signal="internal_failure",
            requested_action="analyze_quality",
            created_at=current - timedelta(hours=2),
            expires_at=current - timedelta(hours=1),
        )
        with self.store._lock():
            state = self.store._read()
            state["receipts"][expired["receipt_digest_sha256"]] = {
                "receipt": expired,
                "state": "READY",
                "received_at_utc": expired["created_at_utc"],
                "lease_id": None,
                "lease_expires_at_utc": None,
                "proposal_id": None,
                "host_envelope": {},
            }
            self.store._write(state)
        self.store.receive(self.receipt)
        proposal = self.store.consume_next(analyzer_version="1.0.0")
        self.assertEqual(proposal["receipt_digest_sha256"], self.receipt["receipt_digest_sha256"])
        self.assertEqual(self.store.status()["pending_receipts"], 0)

    def test_consumed_receipts_do_not_exhaust_queue_lifetime(self) -> None:
        with mock.patch.object(store_module, "MAX_RECEIPTS", 2):
            for index in range(5):
                receipt = dict(self.receipt)
                receipt["receipt_id"] = str(__import__("uuid").uuid4())
                receipt["producer"] = dict(receipt["producer"], package_digest_sha256=f"{index + 1:064x}")
                receipt["receipt_digest_sha256"] = contract.receipt_digest(receipt)
                self.store.consume(receipt, analyzer_version="1.0.0")
        self.assertEqual(self.store.status()["receipt_count"], 0)
        self.assertEqual(self.store.status()["proposal_count"], 5)

    def test_dismissed_proposal_frees_bounded_capacity(self) -> None:
        first = self.store.consume(self.receipt, analyzer_version="1.0.0")
        self.store.dismiss(first["proposal_id"])
        second_receipt = dict(self.receipt)
        second_receipt["receipt_id"] = str(__import__("uuid").uuid4())
        second_receipt["receipt_digest_sha256"] = contract.receipt_digest(second_receipt)
        with mock.patch.object(store_module, "MAX_PROPOSALS", 1):
            second = self.store.consume(second_receipt, analyzer_version="1.0.0")
        self.assertNotEqual(first["proposal_id"], second["proposal_id"])
        self.assertEqual(self.store.status()["proposal_count"], 1)

    def test_no_issue_is_a_local_noop(self) -> None:
        receipt = contract.create_receipt(
            owner="Ian-Tseng",
            repository="example-producer",
            skill="example-producer",
            version="1.2.3",
            package_digest_sha256="e" * 64,
            outcome="completed",
            quality_signal="no_issue",
            requested_action="none",
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        event = {
            "hook_event_name": "Stop",
            "session_id": "session-no-issue",
            "turn_id": "turn-no-issue",
            "stop_hook_active": False,
            "last_assistant_message": contract.format_marker(receipt),
        }
        self.assertEqual(self.store.handle_stop_event(event), {})
        result = self.store.consume(receipt, analyzer_version="1.0.0")
        self.assertEqual(result["status"], "no_action")
        self.assertEqual(self.store.status()["proposal_count"], 0)

    def test_hook_requests_at_most_one_continuation_per_turn(self) -> None:
        message = "done\n" + contract.format_marker(self.receipt)
        event = {
            "hook_event_name": "Stop",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "stop_hook_active": False,
            "last_assistant_message": message,
        }
        first = self.store.handle_stop_event(event)
        second = self.store.handle_stop_event(event)
        self.assertEqual(first["decision"], "block")
        self.assertEqual(second, {})

    def test_hook_recursion_guard_is_a_noop(self) -> None:
        event = {
            "hook_event_name": "Stop",
            "session_id": "session-1",
            "turn_id": "turn-2",
            "stop_hook_active": True,
            "last_assistant_message": contract.format_marker(self.receipt),
        }
        self.assertEqual(self.store.handle_stop_event(event), {})


class QualityLoopCliTests(unittest.TestCase):
    def test_emit_defaults_no_issue_to_no_action(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--format",
                "json",
                "emit",
                "--repository",
                "fixture",
                "--skill",
                "fixture",
                "--version",
                "1.0.0",
                "--package-digest",
                "f" * 64,
                "--outcome",
                "completed",
                "--quality-signal",
                "no_issue",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["receipt"]["requested_action"], "none")

    def test_cross_process_replay_has_one_proposal_and_truthful_status(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        receipt = contract.create_receipt(
            owner="Ian-Tseng",
            repository="process-fixture",
            skill="process-fixture",
            version="1.0.0",
            package_digest_sha256="9" * 64,
            outcome="completed_with_limitations",
            quality_signal="claim_evidence_gap",
            requested_action="analyze_quality",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        marker = contract.format_marker(receipt)
        with tempfile.TemporaryDirectory(prefix="skill-quality-process-") as directory:
            command = [
                sys.executable,
                str(CLI),
                "--format",
                "json",
                "--state-dir",
                directory,
                "consume",
                "--marker",
                marker,
            ]
            processes = [
                subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for _ in range(4)
            ]
            outputs = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(json.loads(stdout))
            status = QualityStore(Path(directory)).status()
        self.assertEqual({item["status"] for item in outputs}, {"QUALITY_PROPOSAL_READY"})
        self.assertEqual({item["proposal_status"] for item in outputs}, {"active"})
        self.assertEqual(len({item["proposal_id"] for item in outputs}), 1)
        self.assertEqual([item["deduplicated"] for item in outputs].count(False), 1)
        self.assertEqual([item["deduplicated"] for item in outputs].count(True), 3)
        self.assertEqual(status["proposal_count"], 1)

    def test_cross_process_distinct_receipts_preserve_every_proposal(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        markers = []
        for index in range(4):
            receipt = contract.create_receipt(
                owner="Ian-Tseng",
                repository=f"distinct-process-fixture-{index}",
                skill=f"distinct-process-fixture-{index}",
                version="1.0.0",
                package_digest_sha256=f"{index + 1}" * 64,
                outcome="completed_with_limitations",
                quality_signal="claim_evidence_gap",
                requested_action="analyze_quality",
                created_at=now,
                expires_at=now + timedelta(minutes=5),
            )
            markers.append(contract.format_marker(receipt))
        with tempfile.TemporaryDirectory(prefix="skill-quality-process-distinct-") as directory:
            processes = []
            for marker in markers:
                command = [
                    sys.executable,
                    str(CLI),
                    "--format",
                    "json",
                    "--state-dir",
                    directory,
                    "consume",
                    "--marker",
                    marker,
                ]
                processes.append(
                    subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                )
            outputs = []
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stderr)
                outputs.append(json.loads(stdout))
            status = QualityStore(Path(directory)).status()
        self.assertEqual(len({item["proposal_id"] for item in outputs}), len(markers))
        self.assertEqual(status["proposal_count"], len(markers))

    def test_oversized_hook_event_is_a_noop(self) -> None:
        event = json.dumps(
            {
                "hook_event_name": "Stop",
                "session_id": "session-oversized",
                "turn_id": "turn-oversized",
                "stop_hook_active": False,
                "last_assistant_message": "x" * 74000,
            }
        )
        with tempfile.TemporaryDirectory(prefix="skill-quality-hook-") as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--format",
                    "json",
                    "--state-dir",
                    directory,
                    "hook-stop",
                ],
                cwd=ROOT,
                text=True,
                input=event,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})

    def test_two_unrelated_producer_fixtures_share_the_closed_contract(self) -> None:
        receipt_schema = json.loads(
            (SKILL_ROOT / "references" / "skill-outcome-receipt.schema.json").read_text(
                encoding="utf-8"
            )
        )
        proposal_schema = json.loads(
            (SKILL_ROOT / "references" / "skill-quality-proposal.schema.json").read_text(
                encoding="utf-8"
            )
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        for fixture_path in sorted((ROOT / "examples" / "quality-loop-producers").glob("*.json")):
            producer = json.loads(fixture_path.read_text(encoding="utf-8"))
            receipt = contract.create_receipt(
                **producer,
                created_at=now,
                expires_at=now + timedelta(minutes=5),
            )
            self.assertFalse(receipt_schema["additionalProperties"])
            self.assertEqual(set(receipt), set(receipt_schema["required"]))
            with tempfile.TemporaryDirectory(prefix="producer-conformance-") as directory:
                proposal = QualityStore(Path(directory)).consume(
                    receipt,
                    analyzer_version="1.0.0",
                )
            proposal.pop("deduplicated")
            self.assertFalse(proposal_schema["additionalProperties"])
            self.assertEqual(set(proposal), set(proposal_schema["required"]))

    def test_offline_conformance_fixture(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill-quality-cli-") as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--format",
                    "json",
                    "--state-dir",
                    directory,
                    "conformance",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "QUALITY_PROPOSAL_READY")
        self.assertTrue(output["replay_deduplicated"])
        self.assertEqual(output["outbound"], "NONE")


if __name__ == "__main__":
    unittest.main()

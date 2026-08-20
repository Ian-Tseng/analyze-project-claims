from __future__ import annotations

import ast
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "analyze-project-claims"
SCRIPTS = SKILL_ROOT / "scripts"
CONSUMER = SCRIPTS / "lifecycle_receipt.py"
sys.path.insert(0, str(SCRIPTS))

PHASES = (
    "RELEASE_A_INSTALL", "RELEASE_A_IDENTITY", "RELEASE_A_ACTIVATION",
    "UPDATE_DRY_RUN", "RELEASE_B_UPDATE", "RELEASE_B_IDENTITY",
    "RELEASE_B_ACTIVATION", "REPORT_PREVIEW", "ROLLBACK_VERIFIED",
    "ROLLBACK_ACTIVATION", "CLEANUP",
)


def digest(value: dict[str, object], field: str) -> str:
    payload = copy.deepcopy(value)
    payload.pop(field, None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def phase_receipt(run_id: str, sequence: int, phase: str, previous: str | None, status: str = "PASS") -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "kind": "LifecyclePhaseReceipt",
        "protocol_version": "1.0",
        "run_id": run_id,
        "sequence": sequence,
        "phase": phase,
        "status": status,
        "evidence_method": "executed_test",
        "started_at": "2026-08-14T10:00:00Z",
        "ended_at": "2026-08-14T10:00:01Z",
        "summary": f"{phase} {status}",
        "pre_identity": {},
        "post_identity": {},
        "mutations": [],
        "network_destinations": [],
        "artifacts": {},
        "error_code": None if status == "PASS" else "ACTIVATION_UNPROVED",
        "previous_receipt_digest": previous,
    }
    value["receipt_digest"] = digest(value, "receipt_digest")
    return value


def lifecycle_receipt(*, status: str = "COMPLETE", fail_phase: str | None = None) -> dict[str, object]:
    run_id = "plv-example123"
    count = len(PHASES)
    if status == "CLEANUP_REQUIRED":
        count -= 1
    elif status == "RELEASE_B_REQUIRED":
        count = 3
    receipts: list[dict[str, object]] = []
    previous = None
    for sequence, phase in enumerate(PHASES[:count], 1):
        phase_status = "FAIL" if phase == fail_phase else "PASS"
        current = phase_receipt(run_id, sequence, phase, previous, phase_status)
        receipts.append(current)
        previous = str(current["receipt_digest"])
        if phase_status != "PASS":
            break
    value: dict[str, object] = {
        "schema_version": 1,
        "kind": "LifecycleVerificationReceipt",
        "protocol_version": "1.0",
        "run_id": run_id,
        "plan_digest": "sha256:" + "1" * 64,
        "verifier": {"name": "product-lifecycle-verifier", "version": "1.0.0", "protocol_version": "1.0", "digest": "sha256:" + "2" * 64},
        "adapter": {"name": "fake-lifecycle-v1", "version": "1.0.0", "protocol_version": "1.0", "digest": "sha256:" + "3" * 64, "network_destinations": []},
        "product": {"product_type": "agent-skill", "repository": "owner/repo", "skill_name": "demo", "skill_path": "skills/demo/SKILL.md"},
        "target": {"mode": "disposable", "state_root": "D:/safe/runs"},
        "status": status,
        "phases": receipts,
        "strongest_safe_claim": "Only the receipt-bounded lifecycle scope is claimed.",
        "limitations": ["ACTIVATION_UNPROVED"] if fail_phase else [],
        "actions_not_performed": ["publish", "report_send", "live_install_mutation"],
        "parent_receipt_digest": None,
        "iteration": 0,
        "resume_digest": "sha256:" + "4" * 64 if status == "RELEASE_B_REQUIRED" else None,
    }
    value["receipt_digest"] = digest(value, "receipt_digest")
    return value


def recovered_receipt() -> dict[str, object]:
    value = lifecycle_receipt(status="RECOVERY_REQUIRED", fail_phase="RELEASE_B_ACTIVATION")
    previous = str(value["phases"][-1]["receipt_digest"])
    for phase in ("ROLLBACK_VERIFIED", "ROLLBACK_ACTIVATION", "CLEANUP"):
        current = phase_receipt(value["run_id"], len(value["phases"]) + 1, phase, previous)
        value["phases"].append(current)
        previous = str(current["receipt_digest"])
    value["status"] = "RECOVERED"
    value["limitations"] = ["ACTIVATION_UNPROVED"]
    value["receipt_digest"] = digest(value, "receipt_digest")
    return value


class LifecycleReceiptConsumerTests(unittest.TestCase):
    def test_packaged_lifecycle_guide_matches_public_guide(self) -> None:
        packaged = SKILL_ROOT / "references" / "lifecycle-verification-receipt.md"
        public = ROOT / "docs" / "LIFECYCLE_RECEIPT_GUIDE.md"
        self.assertTrue(packaged.is_file())
        self.assertEqual(packaged.read_bytes(), public.read_bytes())

    def load_module(self):
        import lifecycle_receipt

        return lifecycle_receipt

    def test_complete_receipt_is_consistent_and_scope_bounded(self) -> None:
        module = self.load_module()
        result = module.interpret_receipt(lifecycle_receipt())
        self.assertEqual(result["status"], "CONSISTENT")
        self.assertEqual(result["check_status"], "PASS")
        self.assertEqual(result["claim_status"], "supported")
        self.assertEqual(result["evidence_method"], "schema_validated")
        self.assertFalse(result["followup_required"])
        module.verify_digest(result, "interpretation_digest")

    def test_failed_phase_emits_one_read_only_followup_request(self) -> None:
        module = self.load_module()
        receipt = lifecycle_receipt(status="RECOVERY_REQUIRED", fail_phase="RELEASE_B_ACTIVATION")
        interpretation = module.interpret_receipt(receipt)
        self.assertEqual(interpretation["status"], "INCONSISTENT")
        self.assertEqual(interpretation["check_status"], "FAIL")
        request = module.build_followup_request(interpretation, receipt, prior_requests=[])
        self.assertEqual(request["allowed_action"], "read_only_plan")
        self.assertEqual(request["iteration"], 1)
        self.assertIn("publish", request["actions_not_authorized"])
        module.verify_digest(request, "request_digest")

    def test_incomplete_receipt_is_an_evidence_gap(self) -> None:
        module = self.load_module()
        result = module.interpret_receipt(lifecycle_receipt(status="CLEANUP_REQUIRED"))
        self.assertEqual(result["status"], "EVIDENCE_GAP")
        self.assertEqual(result["check_status"], "PARTIAL")
        self.assertEqual(result["claim_status"], "partially_supported")

    def test_recovered_receipt_preserves_failure_and_is_not_a_pass(self) -> None:
        module = self.load_module()
        result = module.interpret_receipt(recovered_receipt())
        self.assertEqual(result["status"], "INCONSISTENT")
        self.assertEqual(result["check_status"], "FAIL")
        self.assertEqual(result["finding"]["code"], "ACTIVATION_UNPROVED")
        self.assertTrue(result["followup_required"])

    def test_tampered_aggregate_or_phase_digest_is_rejected(self) -> None:
        module = self.load_module()
        aggregate = lifecycle_receipt()
        aggregate["status"] = "RECOVERY_REQUIRED"
        with self.assertRaisesRegex(module.ReceiptError, "RECEIPT_DIGEST_INVALID"):
            module.interpret_receipt(aggregate)
        phase_tamper = lifecycle_receipt()
        phase_tamper["phases"][0]["summary"] = "tampered"
        phase_tamper["receipt_digest"] = digest(phase_tamper, "receipt_digest")
        with self.assertRaisesRegex(module.ReceiptError, "PHASE_DIGEST_INVALID"):
            module.interpret_receipt(phase_tamper)

    def test_repeated_same_finding_stops_instead_of_recursing(self) -> None:
        module = self.load_module()
        receipt = lifecycle_receipt(status="RECOVERY_REQUIRED", fail_phase="RELEASE_B_ACTIVATION")
        first = module.interpret_receipt(receipt)
        request = module.build_followup_request(first, receipt, prior_requests=[])
        repeated = module.interpret_receipt(receipt, prior_requests=[request])
        self.assertEqual(repeated["status"], "RECONCILIATION_STALLED")
        self.assertFalse(repeated["followup_required"])
        self.assertIsNone(module.build_followup_request(repeated, receipt, prior_requests=[request]))

    def test_maximum_three_distinct_cycles_is_enforced(self) -> None:
        module = self.load_module()
        receipt = lifecycle_receipt(status="RELEASE_B_REQUIRED")
        interpretation = module.interpret_receipt(receipt)
        requests = []
        for index in range(3):
            varied = copy.deepcopy(interpretation)
            varied["finding_signature"] = "sha256:" + str(index + 5) * 64
            varied["interpretation_digest"] = digest(varied, "interpretation_digest")
            request = module.build_followup_request(varied, receipt, prior_requests=requests)
            self.assertIsNotNone(request)
            requests.append(request)
        stopped = module.interpret_receipt(receipt, prior_requests=requests)
        self.assertEqual(stopped["status"], "RECONCILIATION_STALLED")
        self.assertFalse(stopped["followup_required"])

    def test_consumer_is_read_only_and_does_not_import_executor(self) -> None:
        tree = ast.parse(CONSUMER.read_text(encoding="utf-8"), filename=str(CONSUMER))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported.isdisjoint({"subprocess", "product_lifecycle", "lifecycle_verify"}))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path = root / "receipt.json"
            receipt_path.write_text(json.dumps(lifecycle_receipt()), encoding="utf-8")
            before = sorted(path.name for path in root.iterdir())
            result = subprocess.run(
                [sys.executable, str(CONSUMER), "--format", "json", "interpret", "--receipt", str(receipt_path)],
                cwd=root, text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "CONSISTENT")
            self.assertEqual(before, sorted(path.name for path in root.iterdir()))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evidence_bound_fixtures import accepted_map_record


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "analyze-project-claims"
RECORDER = SKILL_ROOT / "scripts" / "record_scan.py"


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class EvidenceBoundScanEdgeCaseTests(unittest.TestCase):
    def run_cli(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RECORDER), *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_map(self, root: Path) -> Path:
        map_root = root / ".claim-audit" / "component-map"
        value = accepted_map_record(
            SKILL_ROOT,
            [
                {
                    "component_id": "tests",
                    "component_type": "validation",
                    "elements": [
                        {
                            "element_id": "contract",
                            "target": "contract test result",
                            "relation_type": "validates",
                            "evidence_locators": [],
                        }
                    ],
                }
            ],
        )
        map_root.mkdir(parents=True)
        (map_root / "accepted-map.json").write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )
        return map_root

    def write_input(
        self,
        root: Path,
        *,
        evidence_items: list[dict[str, object]],
        status: str = "supported",
        bindings: list[dict[str, str]] | None = None,
        limitations: list[dict[str, object]] | None = None,
        strongest: str | None = "contract-passes",
        boundaries: list[str] | None = None,
        no_supported: bool = False,
    ) -> Path:
        value = {
            "schema_version": "2.0",
            "objective": "Audit the persisted contract result.",
            "scope": ["validation"],
            "authority": ["persisted execution receipt"],
            "evidence_items": evidence_items,
            "claims": [
                {
                    "claim_id": "contract-passes",
                    "statement": "The persisted receipt reports that the contract passed.",
                    "element_ref": {
                        "component_id": "tests",
                        "element_id": "contract",
                    },
                    "material": True,
                    "status": status,
                    "rationale": "The status is bounded to the cited persisted result.",
                }
            ],
            "bindings": bindings
            if bindings is not None
            else [
                {
                    "claim_id": "contract-passes",
                    "evidence_id": evidence_items[0]["evidence_id"],
                    "role": "supports",
                }
            ],
            "limitations": limitations or [],
            "summary": {
                "strongest_safe_claim_id": strongest,
                "claim_boundary_ids": boundaries or [],
                "no_supported_claim": no_supported,
            },
            "unresolved_uncertainties": [],
        }
        path = root / "input.json"
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return path

    def validate(self, root: Path, map_root: Path, record: Path) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            root,
            "validate",
            "--record",
            str(record),
            "--map-root",
            str(map_root),
            "--project-root",
            str(root),
        )

    def test_executed_test_rejects_test_source_as_a_run_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-edge-") as temp:
            root = Path(temp)
            map_root = self.write_map(root)
            (root / "tests").mkdir()
            (root / "tests" / "test_contract.py").write_text(
                "def test_contract(): assert True\n", encoding="utf-8"
            )
            record = self.write_input(
                root,
                evidence_items=[
                    {
                        "evidence_id": "test-source",
                        "source": {"kind": "file", "path": "tests/test_contract.py"},
                        "locator": {"kind": "test_case", "value": "test_contract"},
                        "method": "executed_test",
                        "observed_summary": "The test definition exists.",
                    }
                ],
            )
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("EXECUTED_TEST_RECEIPT_REQUIRED", result.stderr)

    def test_executed_test_accepts_a_persisted_receipt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-edge-") as temp:
            root = Path(temp)
            map_root = self.write_map(root)
            (root / "receipts").mkdir()
            (root / "receipts" / "tests.json").write_text(
                json.dumps({"test_contract": {"status": "passed"}}) + "\n",
                encoding="utf-8",
            )
            record = self.write_input(
                root,
                evidence_items=[
                    {
                        "evidence_id": "test-receipt",
                        "source": {"kind": "file", "path": "receipts/tests.json"},
                        "locator": {
                            "kind": "json_pointer",
                            "value": "/test_contract/status",
                        },
                        "method": "executed_test",
                        "observed_summary": "The persisted test receipt reports passed.",
                    }
                ],
            )
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_secret_like_observation_is_rejected_without_echoing_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-edge-") as temp:
            root = Path(temp)
            map_root = self.write_map(root)
            (root / "receipt.json").write_text('{"status":"passed"}\n', encoding="utf-8")
            secret = "ghp_0123456789abcdefghijklmnop"
            record = self.write_input(
                root,
                evidence_items=[
                    {
                        "evidence_id": "receipt",
                        "source": {"kind": "file", "path": "receipt.json"},
                        "locator": {"kind": "json_pointer", "value": "/status"},
                        "method": "schema_validated",
                        "observed_summary": f"Result passed with token {secret}.",
                    }
                ],
            )
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("SENSITIVE_OBSERVATION_REJECTED", result.stderr)
            self.assertNotIn(secret, result.stderr)

    def test_unverifiable_external_source_cannot_support_append(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-edge-") as temp:
            root = Path(temp)
            map_root = self.write_map(root)
            record = self.write_input(
                root,
                evidence_items=[
                    {
                        "evidence_id": "remote-result",
                        "source": {"kind": "https", "url": "https://example.com/result"},
                        "locator": {"kind": "whole_file"},
                        "method": "inspected",
                        "observed_summary": "The remote page states that the contract passed.",
                    }
                ],
            )
            result = self.run_cli(
                root,
                "append",
                "--record",
                str(record),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--log-dir",
                str(root / "history"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("EXTERNAL_EVIDENCE_UNVERIFIABLE", result.stderr)
            self.assertFalse((root / "history").exists())

    def test_partial_claim_requires_named_boundary_in_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-edge-") as temp:
            root = Path(temp)
            map_root = self.write_map(root)
            (root / "receipt.json").write_text('{"status":"passed"}\n', encoding="utf-8")
            evidence = [
                {
                    "evidence_id": "receipt",
                    "source": {"kind": "file", "path": "receipt.json"},
                    "locator": {"kind": "json_pointer", "value": "/status"},
                    "method": "schema_validated",
                    "observed_summary": "The stored status is passed.",
                }
            ]
            limitation = {
                "limitation_id": "single-platform",
                "text": "Only one platform was checked.",
                "claim_ids": ["contract-passes"],
                "evidence_ids": [],
            }
            record = self.write_input(
                root,
                evidence_items=evidence,
                status="partially_supported",
                limitations=[limitation],
            )
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("STRONGEST_CLAIM_UNBOUND", result.stderr)

    def test_integrity_and_report_drift_are_detected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-edge-") as temp:
            root = Path(temp)
            map_root = self.write_map(root)
            (root / "receipt.json").write_text('{"status":"passed"}\n', encoding="utf-8")
            record_input = self.write_input(
                root,
                evidence_items=[
                    {
                        "evidence_id": "receipt",
                        "source": {"kind": "file", "path": "receipt.json"},
                        "locator": {"kind": "json_pointer", "value": "/status"},
                        "method": "schema_validated",
                        "observed_summary": "The stored status is passed.",
                    }
                ],
            )
            append = self.run_cli(
                root,
                "append",
                "--record",
                str(record_input),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--log-dir",
                str(root / "history"),
                "--report-dir",
                str(root / "reports"),
            )
            self.assertEqual(append.returncode, 0, append.stderr)
            receipt = json.loads(append.stdout)
            record_path = Path(receipt["log"])
            report_path = Path(receipt["report"])

            report_path.write_text("out of date\n", encoding="utf-8")
            report_check = self.run_cli(
                root,
                "verify",
                "--record",
                str(record_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--report",
                str(report_path),
                "--format",
                "json",
            )
            self.assertEqual(report_check.returncode, 3, report_check.stderr)
            self.assertIn("REPORT_OUT_OF_DATE", json.loads(report_check.stdout)["codes"])

            persisted = json.loads(record_path.read_text(encoding="utf-8"))
            persisted["claims"][0]["statement"] = "Tampered claim."
            record_path.write_text(json.dumps(persisted, indent=2) + "\n", encoding="utf-8")
            tamper = self.run_cli(root, "verify", "--record", str(record_path))
            self.assertEqual(tamper.returncode, 2)
            self.assertIn("RECORD_INTEGRITY_MISMATCH", tamper.stderr)


if __name__ == "__main__":
    unittest.main()

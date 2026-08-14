from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


class EvidenceBoundScanTests(unittest.TestCase):
    maxDiff = None

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
        record = {
            "schema_version": "1.0",
            "map_id": "component-map-0123456789ab",
            "map_state": "accepted",
            "skill_name": "analyze-project-claims",
            "skill_sha256": hashlib.sha256(
                (SKILL_ROOT / "SKILL.md").read_bytes()
            ).hexdigest(),
            "components": [
                {
                    "component_id": "results",
                    "component_type": "artifact",
                    "elements": [
                        {
                            "element_id": "accuracy",
                            "target": "reported accuracy",
                            "relation_type": "measures",
                            "evidence_locators": [],
                        }
                    ],
                }
            ],
        }
        record["integrity"] = {"canonical_payload_sha256": canonical_sha256(record)}
        map_root.mkdir(parents=True)
        (map_root / "accepted-map.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
        return map_root

    def write_input(self, root: Path, **overrides: object) -> Path:
        value: dict[str, object] = {
            "schema_version": "2.0",
            "objective": "Determine the strongest result claim supported by current evidence.",
            "scope": ["results.json"],
            "authority": ["validation protocol"],
            "evidence_items": [
                {
                    "evidence_id": "result-accuracy",
                    "source": {"kind": "file", "path": "results.json"},
                    "locator": {"kind": "json_pointer", "value": "/accuracy"},
                    "method": "schema_validated",
                    "observed_summary": "The stored result reports accuracy 0.91.",
                }
            ],
            "claims": [
                {
                    "claim_id": "accuracy-reported",
                    "statement": "The stored result reports accuracy 0.91.",
                    "element_ref": {
                        "component_id": "results",
                        "element_id": "accuracy",
                    },
                    "material": True,
                    "status": "supported",
                    "rationale": "A human reviewer matched the declared metric to the stored result.",
                }
            ],
            "bindings": [
                {
                    "claim_id": "accuracy-reported",
                    "evidence_id": "result-accuracy",
                    "role": "supports",
                }
            ],
            "limitations": [],
            "summary": {
                "strongest_safe_claim_id": "accuracy-reported",
                "claim_boundary_ids": [],
                "no_supported_claim": False,
            },
            "unresolved_uncertainties": [
                "This record does not establish out-of-sample benefit."
            ],
        }
        value.update(overrides)
        path = root / "scan-v2.json"
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return path

    def prepare(self, root: Path) -> tuple[Path, Path]:
        (root / "results.json").write_text(
            json.dumps({"accuracy": 0.91, "loss": 0.2}) + "\n",
            encoding="utf-8",
        )
        return self.write_map(root), self.write_input(root)

    def test_validate_and_append_create_exact_evidence_and_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-") as temp:
            root = Path(temp)
            map_root, input_path = self.prepare(root)
            validate = self.run_cli(
                root,
                "validate",
                "--record",
                str(input_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)
            self.assertEqual(json.loads(validate.stdout)["status"], "valid")

            history = root / "history"
            reports = root / "reports"
            append = self.run_cli(
                root,
                "append",
                "--record",
                str(input_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--log-dir",
                str(history),
                "--report-dir",
                str(reports),
            )
            self.assertEqual(append.returncode, 0, append.stderr)
            receipt = json.loads(append.stdout)
            record_path = Path(receipt["log"])
            report_path = Path(receipt["report"])
            record = json.loads(record_path.read_text(encoding="utf-8"))
            evidence = record["evidence_items"][0]
            self.assertEqual(evidence["freshness"], "current")
            self.assertEqual(
                evidence["source"]["sha256"],
                hashlib.sha256((root / "results.json").read_bytes()).hexdigest(),
            )
            self.assertRegex(evidence["selection_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                record["summary"]["strongest_safe_claim_id"],
                "accuracy-reported",
            )
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("Evidence-bound audit record", report)
            self.assertIn("accuracy-reported", report)
            self.assertIn("result-accuracy", report)
            self.assertIn("results.json", report)
            self.assertIn("Semantic review required", report)

            render = self.run_cli(root, "render", "--record", str(record_path))
            self.assertEqual(render.returncode, 0, render.stderr)
            self.assertEqual(render.stdout, report)

    def test_supported_claim_without_support_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-") as temp:
            root = Path(temp)
            map_root, _ = self.prepare(root)
            input_path = self.write_input(root, bindings=[])
            result = self.run_cli(
                root,
                "validate",
                "--record",
                str(input_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("BINDING_MISSING", result.stderr)

    def test_strongest_claim_with_contradiction_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-") as temp:
            root = Path(temp)
            map_root, _ = self.prepare(root)
            bindings = [
                {
                    "claim_id": "accuracy-reported",
                    "evidence_id": "result-accuracy",
                    "role": "supports",
                },
                {
                    "claim_id": "accuracy-reported",
                    "evidence_id": "result-accuracy",
                    "role": "contradicts",
                },
            ]
            input_path = self.write_input(root, bindings=bindings)
            result = self.run_cli(
                root,
                "validate",
                "--record",
                str(input_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("STRONGEST_CLAIM_UNBOUND", result.stderr)

    def test_path_escape_is_rejected_before_append(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-") as temp:
            root = Path(temp)
            map_root, _ = self.prepare(root)
            evidence = [
                {
                    "evidence_id": "result-accuracy",
                    "source": {"kind": "file", "path": "../secret.txt"},
                    "locator": {"kind": "whole_file"},
                    "method": "inspected",
                    "observed_summary": "Unsafe path.",
                }
            ]
            input_path = self.write_input(root, evidence_items=evidence)
            result = self.run_cli(
                root,
                "append",
                "--record",
                str(input_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--log-dir",
                str(root / "history"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("EVIDENCE_PATH_UNSAFE", result.stderr)

    def test_verify_detects_stale_evidence_without_rewriting_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-") as temp:
            root = Path(temp)
            map_root, input_path = self.prepare(root)
            history = root / "history"
            append = self.run_cli(
                root,
                "append",
                "--record",
                str(input_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--log-dir",
                str(history),
            )
            self.assertEqual(append.returncode, 0, append.stderr)
            record_path = Path(json.loads(append.stdout)["log"])
            before = record_path.read_bytes()
            (root / "results.json").write_text('{"accuracy": 0.10}\n', encoding="utf-8")
            verify = self.run_cli(
                root,
                "verify",
                "--record",
                str(record_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--format",
                "json",
            )
            self.assertEqual(verify.returncode, 3, verify.stderr)
            output = json.loads(verify.stdout)
            self.assertEqual(output["status"], "stale")
            self.assertIn("EVIDENCE_DIGEST_MISMATCH", output["codes"])
            self.assertEqual(record_path.read_bytes(), before)
            self.assertEqual(len(list(history.glob("*.json"))), 1)

    def test_v1_record_renders_and_verifies_as_legacy_unbound(self) -> None:
        legacy = ROOT / "validation" / "history" / "20260814T073620422660Z-4823f56d.json"
        render = self.run_cli(ROOT, "render", "--record", str(legacy))
        self.assertEqual(render.returncode, 0, render.stderr)
        self.assertIn("LEGACY_RECORD_UNBOUND", render.stdout)
        verify = self.run_cli(ROOT, "verify", "--record", str(legacy), "--format", "json")
        self.assertEqual(verify.returncode, 3, verify.stderr)
        self.assertEqual(json.loads(verify.stdout)["status"], "legacy_unbound")

    def test_draft_v2_copies_prose_but_invents_no_binding(self) -> None:
        legacy = ROOT / "validation" / "history" / "20260814T073620422660Z-4823f56d.json"
        with tempfile.TemporaryDirectory(prefix="evidence-bound-") as temp:
            root = Path(temp)
            map_root = self.write_map(root)
            output = root / "draft.json"
            result = self.run_cli(
                root,
                "draft-v2",
                "--legacy-record",
                str(legacy),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--output",
                str(output),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            draft = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(draft["bindings"], [])
            self.assertEqual(draft["evidence_items"], [])
            self.assertEqual(draft["claims"][0]["status"], "untested")
            self.assertTrue(draft["summary"]["no_supported_claim"])
            self.assertIsNone(draft["summary"]["strongest_safe_claim_id"])

    def test_preflight_init_and_evidence_digest_reduce_manual_authoring(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-") as temp:
            root = Path(temp)
            map_root, _ = self.prepare(root)
            preflight = self.run_cli(
                root,
                "preflight",
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
            )
            self.assertEqual(preflight.returncode, 0, preflight.stderr)
            self.assertIn("results/accuracy", preflight.stdout)

            draft_path = root / "initialized.json"
            init = self.run_cli(
                root,
                "init",
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--output",
                str(draft_path),
            )
            self.assertEqual(init.returncode, 0, init.stderr)
            initialized = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(initialized["schema_version"], "2.0")
            self.assertEqual(initialized["bindings"], [])

            digest = self.run_cli(
                root,
                "evidence",
                "digest",
                "--source",
                "results.json",
                "--locator",
                "json-pointer:/accuracy",
                "--project-root",
                str(root),
                "--id",
                "result-accuracy",
            )
            self.assertEqual(digest.returncode, 0, digest.stderr)
            output = json.loads(digest.stdout)
            self.assertEqual(output["evidence_item"]["evidence_id"], "result-accuracy")
            self.assertRegex(output["computed_identity"]["source_sha256"], r"^[0-9a-f]{64}$")

    def test_v2_contract_files_are_packaged(self) -> None:
        required = [
            SKILL_ROOT / "assets" / "scan-record-v2.template.json",
            SKILL_ROOT / "references" / "scan-record-v2.schema.json",
            SKILL_ROOT / "references" / "scan-record-output-v2.schema.json",
            SKILL_ROOT / "references" / "evidence-bound-audit-records.md",
            ROOT / "examples" / "scan-input-v2.example.json",
        ]
        self.assertEqual([str(path) for path in required if not path.is_file()], [])
        for path in required[:3]:
            json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import test_evidence_bound_scan_operational as operational


class EvidenceBoundScanSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = operational.EvidenceBoundScanOperationalTests(methodName="test_help_leads_with_v2_subcommands")

    def validate(self, root: Path, map_root: Path, record: Path):
        return self.helper.run_cli(
            root,
            "validate",
            "--record",
            str(record),
            "--map-root",
            str(map_root),
            "--project-root",
            str(root),
        )

    def test_https_fragment_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-security-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            value = json.loads(record.read_text(encoding="utf-8"))
            value["evidence_items"][0]["source"] = {
                "kind": "https",
                "url": "https://example.com/results#access-token",
                "revision": "sha256:immutable",
            }
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("EXTERNAL_EVIDENCE_UNSAFE", result.stderr)

    def test_bidi_format_control_is_rejected_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-security-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            value = json.loads(record.read_text(encoding="utf-8"))
            value["evidence_items"][0]["observed_summary"] = "passed\u202edesliaf"
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("RECORD_TEXT_UNSAFE", result.stderr)

    def test_git_lfs_pointer_is_named_unavailable_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-security-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            (root / "receipt.json").write_text(
                "version https://git-lfs.github.com/spec/v1\n"
                "oid sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
                "size 12345\n",
                encoding="utf-8",
            )
            result = self.helper.append(root, map_root, record, root / "history")
            self.assertEqual(result.returncode, 2)
            self.assertIn("EVIDENCE_SOURCE_UNAVAILABLE", result.stderr)
            self.assertFalse((root / "history").exists())

    def test_record_binds_schema_renderer_and_required_repair(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-security-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            append = self.helper.run_cli(
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
                "--report-dir",
                str(root / "reports"),
            )
            self.assertEqual(append.returncode, 0, append.stderr)
            receipt = json.loads(append.stdout)
            persisted_path = Path(receipt["log"])
            persisted = json.loads(persisted_path.read_text(encoding="utf-8"))
            integrity = persisted["integrity"]
            self.assertRegex(integrity["output_schema_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(integrity["renderer_id"], "evidence-bound-markdown-v1")
            self.assertRegex(integrity["renderer_sha256"], r"^[0-9a-f]{64}$")
            report = Path(receipt["report"]).read_text(encoding="utf-8")
            self.assertIn("Output schema:", report)
            self.assertIn("Renderer:", report)
            self.assertIn("Required repair:", report)

            persisted["integrity"]["output_schema_sha256"] = "0" * 64
            payload = json.loads(json.dumps(persisted))
            payload["integrity"].pop("canonical_payload_sha256")
            persisted["integrity"]["canonical_payload_sha256"] = operational.canonical_sha256(payload)
            persisted_path.write_text(json.dumps(persisted, indent=2) + "\n", encoding="utf-8")
            verify = self.helper.run_cli(
                root,
                "verify",
                "--record",
                str(persisted_path),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--format",
                "json",
            )
            self.assertEqual(verify.returncode, 3, verify.stderr)
            self.assertIn("SCHEMA_IDENTITY_MISMATCH", json.loads(verify.stdout)["codes"])


if __name__ == "__main__":
    unittest.main()

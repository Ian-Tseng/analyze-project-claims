from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import test_evidence_bound_scan_operational as operational


class EvidenceBoundScanInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = operational.EvidenceBoundScanOperationalTests(
            methodName="test_help_leads_with_v2_subcommands"
        )

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

    def rewrite(self, record: Path, mutate) -> None:
        value = json.loads(record.read_text(encoding="utf-8"))
        mutate(value)
        record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def test_context_binding_never_counts_as_support(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-invariant-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            self.rewrite(record, lambda value: value["bindings"][0].update(role="context"))
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("BINDING_MISSING", result.stderr)

    def test_no_supported_sentinel_cannot_hide_supported_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-invariant-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)

            def mutate(value):
                value["summary"] = {
                    "strongest_safe_claim_id": None,
                    "claim_boundary_ids": [],
                    "no_supported_claim": True,
                }

            self.rewrite(record, mutate)
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("STRONGEST_CLAIM_UNBOUND", result.stderr)

    def test_nonmaterial_claim_cannot_be_selected_as_strongest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-invariant-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            self.rewrite(record, lambda value: value["claims"][0].update(material=False))
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("STRONGEST_CLAIM_UNBOUND", result.stderr)

    def test_limit_edges_and_named_limitation_evidence_must_match(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-invariant-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)

            def mutate(value):
                value["claims"][0]["status"] = "partially_supported"
                value["bindings"].append(
                    {
                        "claim_id": "validation-passed",
                        "evidence_id": "validation-receipt",
                        "role": "limits",
                    }
                )
                value["limitations"] = [
                    {
                        "limitation_id": "platform-boundary",
                        "text": "Only one platform was checked.",
                        "claim_ids": ["validation-passed"],
                        "evidence_ids": [],
                    }
                ]
                value["summary"]["claim_boundary_ids"] = ["platform-boundary"]

            self.rewrite(record, mutate)
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("BINDING_MISSING", result.stderr)

    def test_closed_contract_rejects_unknown_nested_field(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-invariant-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            self.rewrite(
                record,
                lambda value: value["claims"][0].update(automatic_proof=True),
            )
            result = self.validate(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("RECORD_SCHEMA_UNSUPPORTED", result.stderr)

    def test_duplicate_and_dangling_identifiers_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-invariant-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            original = json.loads(record.read_text(encoding="utf-8"))
            cases = {
                "duplicate evidence_id": lambda value: value["evidence_items"].append(
                    json.loads(json.dumps(value["evidence_items"][0]))
                ),
                "dangling claim ref": lambda value: value["bindings"][0].update(
                    claim_id="missing-claim"
                ),
                "contradicted without counterevidence": lambda value: value["claims"][0].update(
                    status="contradicted"
                ),
            }
            for label, mutate in cases.items():
                with self.subTest(label=label):
                    value = json.loads(json.dumps(original))
                    mutate(value)
                    record.write_text(
                        json.dumps(value, indent=2) + "\n", encoding="utf-8"
                    )
                    result = self.validate(root, map_root, record)
                    self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()

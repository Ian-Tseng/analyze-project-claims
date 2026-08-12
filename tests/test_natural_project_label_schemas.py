from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NaturalProjectLabelSchemaTests(unittest.TestCase):
    def test_human_label_contracts_are_machine_readable_and_hash_bound(self) -> None:
        schema_root = ROOT / "evaluation" / "schemas"
        annotation = json.loads(
            (schema_root / "independent-annotation.schema.json").read_text(encoding="utf-8")
        )
        gold = json.loads(
            (schema_root / "natural-adjudicated-gold.schema.json").read_text(encoding="utf-8")
        )
        commitment = json.loads(
            (schema_root / "natural-label-commitment.schema.json").read_text(encoding="utf-8")
        )
        calibration_discussion = json.loads(
            (schema_root / "annotation-calibration-discussion.schema.json").read_text(
                encoding="utf-8"
            )
        )
        calibration_commitment = json.loads(
            (schema_root / "annotation-calibration-commitment.schema.json").read_text(
                encoding="utf-8"
            )
        )
        codebook_commitment = json.loads(
            (schema_root / "natural-codebook-commitment.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("snapshot_sha256", annotation["required"])
        self.assertIn("annotator_id", annotation["required"])
        self.assertEqual(annotation["properties"]["completed"]["const"], True)
        self.assertIn("source_annotation_sha256", gold["required"])
        self.assertEqual(gold["properties"]["gold_frozen"]["const"], True)
        self.assertIn("label_set_sha256", commitment["required"])
        self.assertIn("annotation_codebook_sha256", commitment["required"])
        self.assertIn("calibration_set_sha256", commitment["required"])
        self.assertIn("study_codebook_binding_sha256", commitment["required"])
        self.assertEqual(commitment["properties"]["paper_table_eligible"]["const"], False)
        self.assertEqual(calibration_discussion["properties"]["status"]["const"], "complete")
        self.assertIn("calibration_set_sha256", calibration_commitment["required"])
        self.assertEqual(
            calibration_commitment["properties"]["evidence_role"]["const"],
            "training_only",
        )
        self.assertIn("study_codebook_binding_sha256", codebook_commitment["required"])
        self.assertEqual(
            codebook_commitment["properties"][
                "calibration_evidence_excluded_from_study"
            ]["const"],
            True,
        )

    def test_codebook_preserves_claim_and_operator_boundaries(self) -> None:
        codebook = (ROOT / "evaluation" / "annotation-codebook.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("same-scope counterevidence", codebook)
        self.assertIn("exact two-candidate complement over the three-state label domain", codebook)
        self.assertIn("may contain zero `candidate_findings`", codebook)
        self.assertIn("invalid_label_commitment", codebook)


if __name__ == "__main__":
    unittest.main()

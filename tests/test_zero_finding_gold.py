from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evaluation" / "scripts" / "cross_project_reliability.py"


def load_module():
    spec = importlib.util.spec_from_file_location("cross_project_zero_gold", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ZeroFindingGoldTests(unittest.TestCase):
    def test_empty_gold_is_valid_and_undefined_recall_is_not_fabricated(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            labels = root / "gold.json"
            labels.write_text(
                json.dumps(
                    {
                        "schema_version": "APC_GOLD_LABELS_V1",
                        "project_id": "zero_gold",
                        "element_inventory": [
                            {"element_id": "readme", "path": "README.md"}
                        ],
                        "gold_findings": [],
                    }
                ),
                encoding="utf-8",
            )
            config = {
                "projects": [
                    {"id": "zero_gold", "gold_labels": "gold.json"}
                ]
            }
            gold = module._load_gold(config, root, "zero_gold")

        spec = {
            "spec_id": "zero-agent_only-family-r1",
            "project_id": "zero_gold",
            "condition_id": "agent_only",
            "agent_family_id": "family",
            "repeat_id": "r1",
        }
        submission = {
            "findings": [],
            "elapsed_seconds": 1.0,
            "input_tokens": 10,
            "output_tokens": 2,
        }
        result = module._score_spec(spec, submission, {"matches": []}, gold)

        self.assertIsNone(result["finding_precision"])
        self.assertIsNone(result["finding_recall"])
        self.assertIsNone(result["finding_f1"])
        self.assertIsNone(result["severe_finding_recall"])
        self.assertEqual(result["false_positive_element_rate"], 0.0)

    def test_false_positive_on_empty_gold_is_penalized(self) -> None:
        module = load_module()
        spec = {
            "spec_id": "zero-agent_only-family-r1",
            "project_id": "zero_gold",
            "condition_id": "agent_only",
            "agent_family_id": "family",
            "repeat_id": "r1",
        }
        submission = {
            "findings": [{"finding_id": "F-1", "element_id": "readme"}],
            "elapsed_seconds": 1.0,
            "input_tokens": 10,
            "output_tokens": 2,
        }
        adjudication = {
            "matches": [
                {
                    "finding_id": "F-1",
                    "gold_finding_id": None,
                    "repair_correct": False,
                    "provenance_preserved": True,
                }
            ]
        }
        gold = {
            "project_id": "zero_gold",
            "element_inventory": [{"element_id": "readme", "path": "README.md"}],
            "gold_findings": [],
        }
        result = module._score_spec(spec, submission, adjudication, gold)

        self.assertEqual(result["finding_precision"], 0.0)
        self.assertIsNone(result["finding_recall"])
        self.assertEqual(result["finding_f1"], 0.0)
        self.assertEqual(result["false_positive_element_rate"], 1.0)

    def test_matched_deltas_preserve_undefined_metrics(self) -> None:
        module = load_module()
        rows = []
        for condition_id in ("agent_only", "generic_checklist", "skill_assisted"):
            rows.append(
                {
                    "project_id": "zero_gold",
                    "agent_family_id": "family",
                    "repeat_id": "r1",
                    "condition_id": condition_id,
                    "finding_f1": None,
                    "severe_finding_recall": None,
                }
            )

        comparisons = module._comparison_deltas(rows)
        self.assertEqual(len(comparisons), 2)
        self.assertTrue(
            all(row["macro_mean_finding_f1_delta"] is None for row in comparisons)
        )
        self.assertTrue(
            all(
                row["macro_mean_severe_finding_recall_delta"] is None
                for row in comparisons
            )
        )


if __name__ == "__main__":
    unittest.main()

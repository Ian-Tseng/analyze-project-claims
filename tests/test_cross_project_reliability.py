from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT / "evaluation"
SCRIPT = EVALUATION / "scripts" / "cross_project_reliability.py"
CONFIG = EVALUATION / "configs" / "dry-run.json"


def load_module():
    spec = importlib.util.spec_from_file_location("cross_project_reliability_public", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CrossProjectReliabilityTests(unittest.TestCase):
    def test_dry_run_completes_without_authorizing_reliability(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            result = module.run_dry_run(CONFIG, Path(temporary))
            run_dir = Path(result["run_dir"])
            summary = json.loads((run_dir / "summaries/metrics.json").read_text(encoding="utf-8"))
            completion = json.loads(
                (run_dir / "controller/experiment_complete.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(summary["spec_results"]), 12)
            self.assertEqual(summary["analysis_unit"], "project_condition_family_repeat")
            self.assertFalse(summary["paper_table_eligible"])
            self.assertFalse(summary["general_reliability_proved"])
            self.assertTrue(completion["accepted_complete"])
            self.assertEqual(completion["scientific_state"], "untested")

    def test_runtime_output_does_not_change_scientific_identity(self) -> None:
        module = load_module()
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        changed = json.loads(json.dumps(config))
        changed["runtime"]["output_root"] = "different/runtime/root"
        self.assertEqual(
            module.scientific_config_hash(config, EVALUATION),
            module.scientific_config_hash(changed, EVALUATION),
        )


if __name__ == "__main__":
    unittest.main()

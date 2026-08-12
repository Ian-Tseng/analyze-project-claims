from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "analyze-project-claims"
MAPPER = SKILL / "scripts" / "reconcile_component_map.py"
RECORDER = SKILL / "scripts" / "record_scan.py"


class StrictEvidenceContractTests(unittest.TestCase):
    def run_cli(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_mapper_rejects_test_only_element_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            tests = project / "tests"
            tests.mkdir()
            (tests / "test_behavior.py").write_text("assert True\n", encoding="utf-8")
            observation = {
                "objective": "Map a test-backed element.",
                "scope": ["tests/test_behavior.py"],
                "authority": ["tests/test_behavior.py"],
                "components": [
                    {
                        "component_id": "component-a",
                        "component_type": "code",
                        "elements": [
                            {
                                "element_id": "element-a",
                                "target": "Behavior A",
                                "evidence": [
                                    {"source": "tests/test_behavior.py", "locator": "assert True"}
                                ],
                            }
                        ],
                    }
                ],
            }
            path = project / "observation.json"
            path.write_text(json.dumps(observation), encoding="utf-8")
            result = self.run_cli(
                MAPPER,
                "reconcile",
                "--observation",
                str(path),
                "--map-root",
                str(Path(temporary) / "map"),
                "--project-root",
                str(project),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("non-test dependency", result.stderr)

    def test_mapper_rejects_element_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            (project / "source.py").write_text("VALUE = 1\n", encoding="utf-8")
            observation = {
                "objective": "Map an ungrounded element.",
                "scope": ["source.py"],
                "authority": ["source.py"],
                "components": [
                    {
                        "component_id": "component-a",
                        "component_type": "code",
                        "elements": [{"element_id": "element-a", "target": "Behavior A"}],
                    }
                ],
            }
            path = project / "observation.json"
            path.write_text(json.dumps(observation), encoding="utf-8")
            result = self.run_cli(
                MAPPER,
                "reconcile",
                "--observation",
                str(path),
                "--map-root",
                str(Path(temporary) / "map"),
                "--project-root",
                str(project),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("evidence", result.stderr)

    def test_recorder_rejects_unknown_element_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            record = {
                "objective": "Record a strict scan.",
                "scope": ["source.py"],
                "authority": ["source.py"],
                "components": [
                    {
                        "component_id": "component-a",
                        "component_type": "code",
                        "elements": [
                            {
                                "element_id": "element-a",
                                "target": "Behavior A",
                                "method": "inspected",
                                "check_status": "PASS",
                                "claim_status": "supported",
                                "evidence": [
                                    {"source": "source.py", "locator": "VALUE", "observed": 1}
                                ],
                                "safe_interpretation": "The source declares VALUE.",
                                "required_repair": None,
                                "unexpected": True,
                            }
                        ],
                    }
                ],
                "strongest_safe_claim": "The source was inspected.",
                "claim_boundary": "No execution evidence.",
                "unresolved_uncertainties": [],
            }
            path = Path(temporary) / "record.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            result = self.run_cli(
                RECORDER,
                "--record",
                str(path),
                "--log-dir",
                str(Path(temporary) / "history"),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown fields", result.stderr)


if __name__ == "__main__":
    unittest.main()

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
MAPPER = SKILL_ROOT / "scripts" / "reconcile_component_map.py"


def observation(target: str = "field:x") -> dict[str, object]:
    return {
        "objective": "Audit an example project.",
        "scope": ["source.txt"],
        "authority": ["source.txt"],
        "components": [
            {
                "component_id": "component-a",
                "component_type": "module",
                "elements": [
                    {
                        "element_id": "element-a",
                        "target": target,
                        "relation_type": "contains",
                        "method": "inspected",
                        "check_status": "PASS",
                        "claim_status": "supported",
                        "evidence": [
                            {"source": "source.txt", "locator": "line:1", "observed": True}
                        ],
                        "safe_interpretation": "The element is declared.",
                        "required_repair": None,
                    }
                ],
            }
        ],
        "strongest_safe_claim": "The structure was inspected.",
        "claim_boundary": "No runtime behavior was tested.",
        "unresolved_uncertainties": [],
    }


class ComponentMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="component-map-test-")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.source = self.project / "source.txt"
        self.source.write_text("version one\n", encoding="utf-8")
        self.map_root = self.root / "map"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_observation(self, target: str = "field:x") -> Path:
        path = self.project / "observation.json"
        path.write_text(json.dumps(observation(target)), encoding="utf-8")
        return path

    def write_directory_observation(self) -> Path:
        payload = observation()
        payload["scope"] = ["source-tree"]
        payload["authority"] = ["source-tree"]
        payload["components"][0]["elements"][0]["evidence"][0]["source"] = (
            "source-tree"
        )
        path = self.project / "directory-observation.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def run_cli(self, *args: str) -> tuple[subprocess.CompletedProcess[str], dict | None]:
        result = subprocess.run(
            [sys.executable, str(MAPPER), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return result, json.loads(result.stdout) if result.returncode == 0 else None

    def reconcile(self, target: str = "field:x"):
        return self.run_cli(
            "reconcile",
            "--observation",
            str(self.write_observation(target)),
            "--map-root",
            str(self.map_root),
            "--project-root",
            str(self.project),
        )

    def bootstrap_and_accept(self) -> str:
        result, output = self.reconcile()
        self.assertEqual(result.returncode, 0, result.stderr)
        result, accepted = self.run_cli(
            "accept",
            "--candidate",
            output["candidate"],
            "--map-root",
            str(self.map_root),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return accepted["accepted_map"]

    def test_template_uses_schema_shaped_hash_placeholders(self) -> None:
        template = json.loads(
            (SKILL_ROOT / "assets" / "component-map.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertRegex(template["skill_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            template["source_snapshot"][0]["sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertRegex(
            template["integrity"]["canonical_payload_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_observation_template_preserves_evidence_locators(self) -> None:
        template_path = (
            SKILL_ROOT / "assets" / "component-map-observation.template.json"
        )
        payload = json.loads(template_path.read_text(encoding="utf-8"))
        observation_path = self.project / "template-observation.json"
        observation_path.write_text(json.dumps(payload), encoding="utf-8")
        result, output = self.run_cli(
            "reconcile",
            "--observation",
            str(observation_path),
            "--map-root",
            str(self.map_root),
            "--project-root",
            str(self.project),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate = json.loads(Path(output["candidate"]).read_text(encoding="utf-8"))
        self.assertEqual(
            candidate["components"][0]["elements"][0]["evidence_locators"],
            [{"source": "source.txt", "locator": "line:1"}],
        )

    def test_output_map_locator_field_is_rejected_as_observation_input(self) -> None:
        payload = observation()
        element = payload["components"][0]["elements"][0]
        element["evidence_locators"] = element.pop("evidence")
        path = self.project / "output-shaped-observation.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result, _ = self.run_cli(
            "reconcile",
            "--observation",
            str(path),
            "--map-root",
            str(self.map_root),
            "--project-root",
            str(self.project),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("evidence_locators", result.stderr)
        self.assertIn("evidence", result.stderr)

    def test_accept_rejects_candidate_missing_schema_required_target(self) -> None:
        result, output = self.reconcile()
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate_path = Path(output["candidate"])
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        candidate["components"][0]["elements"][0].pop("target")
        payload = dict(candidate)
        payload.pop("integrity")
        candidate["integrity"] = {
            "canonical_payload_sha256": hashlib.sha256(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        }
        candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
        accepted, _ = self.run_cli(
            "accept",
            "--candidate",
            str(candidate_path),
            "--map-root",
            str(self.map_root),
        )
        self.assertEqual(accepted.returncode, 2)
        self.assertIn("target", accepted.stderr)
        self.assertFalse((self.map_root / "accepted-map.json").exists())

    def test_observation_schema_enum_violation_is_rejected(self) -> None:
        payload = observation()
        payload["components"][0]["elements"][0]["check_status"] = "DONE"
        path = self.project / "invalid-status-observation.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result, _ = self.run_cli(
            "reconcile",
            "--observation",
            str(path),
            "--map-root",
            str(self.map_root),
            "--project-root",
            str(self.project),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("check_status", result.stderr)

    def test_missing_map_bootstraps_provisional(self) -> None:
        result, output = self.reconcile()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["action"], "bootstrapped_provisional")
        self.assertFalse((self.map_root / "accepted-map.json").exists())

    def test_valid_map_is_checked_without_rebuild(self) -> None:
        accepted = self.bootstrap_and_accept()
        before = hashlib.sha256(Path(accepted).read_bytes()).hexdigest()
        result, output = self.reconcile()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["action"], "checked_unchanged")
        self.assertIsNone(output["candidate"])
        self.assertEqual(hashlib.sha256(Path(accepted).read_bytes()).hexdigest(), before)

    def test_stale_source_produces_delta(self) -> None:
        accepted = self.bootstrap_and_accept()
        before = hashlib.sha256(Path(accepted).read_bytes()).hexdigest()
        self.source.write_text("version two\n", encoding="utf-8")
        result, output = self.reconcile()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["action"], "drift_detected")
        self.assertTrue(output["changes"]["source_changes"])
        self.assertEqual(hashlib.sha256(Path(accepted).read_bytes()).hexdigest(), before)

    def test_directory_hash_ignores_generated_python_cache_files(self) -> None:
        source_tree = self.project / "source-tree"
        source_tree.mkdir()
        (source_tree / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        observation_path = self.write_directory_observation()
        result, output = self.run_cli(
            "reconcile",
            "--observation",
            str(observation_path),
            "--map-root",
            str(self.map_root),
            "--project-root",
            str(self.project),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result, _ = self.run_cli(
            "accept",
            "--candidate",
            output["candidate"],
            "--map-root",
            str(self.map_root),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        cache = source_tree / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-312.pyc").write_bytes(b"generated bytecode")
        (source_tree / "module.pyc").write_bytes(b"legacy generated bytecode")
        (source_tree / "module.pyo").write_bytes(b"optimized generated bytecode")

        result, output = self.run_cli(
            "reconcile",
            "--observation",
            str(observation_path),
            "--map-root",
            str(self.map_root),
            "--project-root",
            str(self.project),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["action"], "checked_unchanged")
        self.assertEqual(output["changes"]["source_changes"], [])

    def test_directory_hash_detects_regular_file_changes(self) -> None:
        source_tree = self.project / "source-tree"
        source_tree.mkdir()
        (source_tree / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        observation_path = self.write_directory_observation()
        result, output = self.run_cli(
            "reconcile",
            "--observation",
            str(observation_path),
            "--map-root",
            str(self.map_root),
            "--project-root",
            str(self.project),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result, _ = self.run_cli(
            "accept",
            "--candidate",
            output["candidate"],
            "--map-root",
            str(self.map_root),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        (source_tree / "new-source.txt").write_text("new source\n", encoding="utf-8")
        result, output = self.run_cli(
            "reconcile",
            "--observation",
            str(observation_path),
            "--map-root",
            str(self.map_root),
            "--project-root",
            str(self.project),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["action"], "drift_detected")
        self.assertEqual(len(output["changes"]["source_changes"]), 1)

    def test_conflict_produces_candidate_without_overwrite(self) -> None:
        accepted = self.bootstrap_and_accept()
        before = hashlib.sha256(Path(accepted).read_bytes()).hexdigest()
        result, output = self.reconcile("field:y")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["action"], "conflict_detected")
        self.assertEqual(output["changes"]["changed_elements"][0]["fields"], ["target"])
        self.assertEqual(hashlib.sha256(Path(accepted).read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()

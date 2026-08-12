from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evaluation" / "scripts" / "annotation_calibration.py"
PILOT_SCRIPT_DIR = SCRIPT.parent


def load_module():
    sys.path.insert(0, str(PILOT_SCRIPT_DIR))
    try:
        spec = importlib.util.spec_from_file_location("annotation_calibration_public", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(PILOT_SCRIPT_DIR))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calibration_selection(codebook_sha256: str) -> dict:
    commit = "a" * 40
    return {
        "schema_version": "APC_ANNOTATION_CALIBRATION_SELECTION_V1",
        "selection_id": "apc-annotation-calibration-v1",
        "phase": "annotation_calibration",
        "evidence_role": "training_only",
        "claim_boundary": "Practice labels may refine the codebook only and cannot support study results.",
        "paper_table_eligible": False,
        "general_reliability_proved": False,
        "reuse_in_development_or_confirmation_prohibited": True,
        "excluded_study_selection_ids": ["apc-natural-development-pilot-v1"],
        "codebook": {
            "path": "evaluation/annotation-codebook.md",
            "sha256": codebook_sha256,
        },
        "packet_limits": {
            "maximum_files_per_project": 100,
            "maximum_bytes_per_project": 100000,
        },
        "annotator_slots": [
            {
                "id": "human_calibrator_a",
                "kind": "human",
                "independent_first_pass": True,
                "condition_blinded": True,
            },
            {
                "id": "human_calibrator_b",
                "kind": "human",
                "independent_first_pass": True,
                "condition_blinded": True,
            },
        ],
        "project": {
            "id": "practice_project",
            "repository_url": "https://github.com/example/practice-project",
            "commit_sha": commit,
            "origin": "natural_external",
            "primary_language": "Python",
            "task_stratum": "practice_library",
            "license": {
                "spdx_ids": ["BSD-3-Clause"],
                "file_paths": ["LICENSE"],
                "evidence_urls": [
                    f"https://github.com/example/practice-project/blob/{commit}/LICENSE"
                ],
            },
            "public_distribution": {"include_source_snapshot": False},
        },
    }


def create_snapshot(root: Path, value: dict) -> None:
    project = value["project"]
    project_root = root / project["id"]
    project_root.mkdir(parents=True)
    (project_root / "README.md").write_text("# practice\n", encoding="utf-8")
    license_path = project_root / "LICENSE"
    license_path.write_text("BSD fixture\n", encoding="utf-8")
    provenance = {
        "schema_version": "APC_PINNED_PROJECT_SOURCE_V1",
        "project_id": project["id"],
        "repository_url": project["repository_url"],
        "commit_sha": project["commit_sha"],
        "archive_url": (
            project["repository_url"].replace("github.com", "codeload.github.com")
            + f"/zip/{project['commit_sha']}"
        ),
        "archive_sha256": "b" * 64,
        "acquired_at": "2026-08-10T00:00:00Z",
        "license_file_sha256": {"LICENSE": sha256(license_path)},
    }
    (project_root / ".apc-source.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )


class AnnotationCalibrationTests(unittest.TestCase):
    def test_accepts_one_project_only_with_nonstudy_exclusion_contract(self) -> None:
        module = load_module()
        value = calibration_selection("c" * 64)
        result = module.validate_calibration_selection(value)

        self.assertEqual(result["project_count"], 1)
        self.assertTrue(result["calibration_only"])
        self.assertFalse(result["paper_table_eligible"])

        value["reuse_in_development_or_confirmation_prohibited"] = False
        with self.assertRaisesRegex(module.ContractError, "reuse"):
            module.validate_calibration_selection(value)

    def test_rejects_overlap_with_frozen_development_projects(self) -> None:
        module = load_module()
        value = calibration_selection("c" * 64)
        value["project"]["repository_url"] = "https://github.com/pallets/itsdangerous"
        with self.assertRaisesRegex(module.ContractError, "development pilot"):
            module.validate_calibration_selection(value)

    def test_prepares_two_practice_packets_and_never_an_execution_gate(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            codebook = temporary_root / "annotation-codebook.md"
            codebook.write_text("# practice codebook\n", encoding="utf-8")
            value = calibration_selection(sha256(codebook))
            selection_path = temporary_root / "selection.json"
            selection_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            snapshot_root = temporary_root / "snapshots"
            create_snapshot(snapshot_root, value)

            result = module.prepare_calibration_workspace(
                selection_path,
                snapshot_root,
                temporary_root / "runs",
                codebook,
            )
            run_dir = Path(result["run_dir"])
            manifest = json.loads(
                (run_dir / "controller" / "calibration_manifest.json").read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(result["annotation_packet_count"], 2)
            self.assertEqual(manifest["evidence_role"], "training_only")
            self.assertTrue(manifest["excluded_from_development"])
            self.assertTrue(manifest["excluded_from_confirmation"])
            self.assertEqual(manifest["calibration_state"], "pending_human_practice")
            self.assertFalse((run_dir / "controller" / "execution_gate.json").exists())
            self.assertTrue((run_dir / "review" / "calibration_discussion.template.json").is_file())


if __name__ == "__main__":
    unittest.main()

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
HELPERS = Path(__file__).with_name("test_annotation_calibration.py")


def load_path(name: str, path: Path):
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPT.parent))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_calibration_run(root: Path):
    module = load_path("annotation_calibration_freeze", SCRIPT)
    helpers = load_path("annotation_calibration_helpers", HELPERS)
    codebook = root / "annotation-codebook.md"
    codebook.parent.mkdir(parents=True, exist_ok=True)
    codebook.write_text("# frozen practice codebook\n", encoding="utf-8")
    selection = helpers.calibration_selection(sha256(codebook))
    selection_path = root / "selection.json"
    selection_path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    snapshot_root = root / "snapshots"
    helpers.create_snapshot(snapshot_root, selection)
    prepared = module.prepare_calibration_workspace(
        selection_path, snapshot_root, root / "runs", codebook
    )
    return module, selection, Path(prepared["run_dir"]), codebook


def write_completed_practice_annotations(module, selection: dict, run_dir: Path) -> dict[str, str]:
    source = json.loads(
        (run_dir / "controller" / "source_manifest.json").read_text(encoding="utf-8")
    )
    snapshot_sha256 = source["projects"][0]["snapshot_sha256"]
    project_id = selection["project"]["id"]
    hashes: dict[str, str] = {}
    for index, slot in enumerate(selection["annotator_slots"], start=1):
        relative = f"{slot['id']}/{project_id}.json"
        path = run_dir / "review" / "raw_labels" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        artifact = {
            "schema_version": "APC_INDEPENDENT_ANNOTATION_V1",
            "selection_sha256": module.canonical_hash(selection),
            "project_id": project_id,
            "annotator_slot_id": slot["id"],
            "snapshot_sha256": snapshot_sha256,
            "annotator_id": f"practice-human-{index}",
            "completed": True,
            "human_attestation": {
                "human_annotator": True,
                "independent": True,
                "condition_blinded": True,
                "no_agent_outputs_reviewed": True,
                "attested_at": "2026-08-10T01:00:00Z",
            },
            "element_inventory": [
                {
                    "element_id": "practice-readme",
                    "component_id": "project_documentation",
                    "path": "README.md",
                    "element_type": "document",
                    "observed_state": "inspected",
                }
            ],
            "candidate_findings": [],
            "notes": "Synthetic calibration fixture only.",
        }
        path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
        hashes[relative] = sha256(path)
    return hashes


def complete_and_freeze_calibration(root: Path):
    module, selection, run_dir, codebook = prepare_calibration_run(root)
    raw_hashes = write_completed_practice_annotations(module, selection, run_dir)
    preflight = module.calibration_label_preflight(run_dir)
    assert preflight["raw_label_sha256"] == raw_hashes
    discussion = {
        "schema_version": "APC_ANNOTATION_CALIBRATION_DISCUSSION_V1",
        "selection_sha256": module.canonical_hash(selection),
        "codebook_initial_sha256": sha256(codebook),
        "status": "complete",
        "independent_annotation_sha256": raw_hashes,
        "disagreement_items": [],
        "codebook_decisions": [],
        "codebook_revised": False,
        "codebook_final_sha256": sha256(codebook),
        "completed_at": "2026-08-10T02:00:00Z",
        "reuse_in_development_or_confirmation_prohibited": True,
        "paper_table_eligible": False,
        "general_reliability_proved": False,
    }
    discussion_path = run_dir / "review" / "calibration_discussion.json"
    discussion_path.write_text(json.dumps(discussion, indent=2) + "\n", encoding="utf-8")
    commitment = module.freeze_calibration(run_dir, codebook)
    return module, selection, run_dir, codebook, commitment


class AnnotationCalibrationFreezeTests(unittest.TestCase):
    def test_freeze_requires_exact_two_completed_human_first_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module, _, run_dir, codebook = prepare_calibration_run(Path(temporary))
            with self.assertRaisesRegex(module.ContractError, "missing calibration annotation"):
                module.freeze_calibration(run_dir, codebook)

    def test_freeze_binds_labels_discussion_and_final_codebook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module, _, run_dir, codebook, commitment = complete_and_freeze_calibration(
                Path(temporary)
            )
            self.assertEqual(commitment["commitment_state"], "frozen")
            self.assertEqual(commitment["raw_annotation_count"], 2)
            self.assertEqual(commitment["codebook_final_sha256"], sha256(codebook))
            self.assertRegex(commitment["calibration_set_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue((run_dir / "protocol" / "final-annotation-codebook.md").is_file())
            status = module.calibration_status(run_dir)
            self.assertEqual(status["calibration_state"], "complete")
            self.assertFalse(status["human_action_required"])

    def test_status_rejects_post_freeze_annotation_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module, selection, run_dir, _, _ = complete_and_freeze_calibration(Path(temporary))
            project_id = selection["project"]["id"]
            path = run_dir / "review" / "raw_labels" / "human_calibrator_a" / f"{project_id}.json"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(module.ContractError, "calibration commitment mismatch"):
                module.calibration_status(run_dir)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evaluation" / "scripts" / "natural_project_pilot.py"
HELPERS = Path(__file__).with_name("test_natural_project_pilot.py")
CALIBRATION_HELPERS = Path(__file__).with_name("test_annotation_calibration_freeze.py")


def load_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_run(temporary_root: Path):
    module = load_path("natural_project_pilot_freeze", SCRIPT)
    helpers = load_path("natural_project_pilot_helpers", HELPERS)
    value = helpers.selection()
    selection_path = temporary_root / "selection.json"
    selection_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    snapshot_root = temporary_root / "snapshots"
    helpers.create_snapshots(snapshot_root, value)
    result = module.prepare_annotation_workspace(
        selection_path, snapshot_root, temporary_root / "runs"
    )
    run_dir = Path(result["run_dir"])
    calibration_helpers = load_path(
        "natural_project_calibration_binding_helpers", CALIBRATION_HELPERS
    )
    _, _, calibration_run, _, _ = calibration_helpers.complete_and_freeze_calibration(
        temporary_root / "calibration"
    )
    module.bind_codebook(run_dir, calibration_run)
    return module, value, run_dir


def write_completed_annotations(module, value: dict, run_dir: Path) -> dict[str, str]:
    source = json.loads(
        (run_dir / "controller" / "source_manifest.json").read_text(encoding="utf-8")
    )
    snapshots = {row["project_id"]: row["snapshot_sha256"] for row in source["projects"]}
    hashes: dict[str, str] = {}
    for slot_index, slot in enumerate(value["annotator_slots"], start=1):
        for project in value["projects"]:
            relative = f"{slot['id']}/{project['id']}.json"
            path = run_dir / "review" / "raw_labels" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            artifact = {
                "schema_version": "APC_INDEPENDENT_ANNOTATION_V1",
                "selection_sha256": module.canonical_hash(value),
                "project_id": project["id"],
                "annotator_slot_id": slot["id"],
                "snapshot_sha256": snapshots[project["id"]],
                "annotator_id": f"independent-human-{slot_index}",
                "completed": True,
                "human_attestation": {
                    "human_annotator": True,
                    "independent": True,
                    "condition_blinded": True,
                    "no_agent_outputs_reviewed": True,
                    "attested_at": "2026-08-09T01:00:00Z",
                },
                "element_inventory": [
                    {
                        "element_id": f"{project['id']}-readme",
                        "component_id": "project_documentation",
                        "path": "README.md",
                        "element_type": "document",
                        "observed_state": "inspected",
                    }
                ],
                "candidate_findings": [],
                "notes": "No inconsistency identified in this synthetic fixture.",
            }
            path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
            hashes[relative] = sha256(path)
    return hashes


def write_adjudicated_gold(
    module,
    value: dict,
    run_dir: Path,
    raw_hashes: dict[str, str],
) -> None:
    source = json.loads(
        (run_dir / "controller" / "source_manifest.json").read_text(encoding="utf-8")
    )
    snapshots = {row["project_id"]: row["snapshot_sha256"] for row in source["projects"]}
    for project in value["projects"]:
        path = run_dir / "review" / "gold" / f"{project['id']}.json"
        artifact = {
            "schema_version": "APC_BLINDED_ADJUDICATED_GOLD_V1",
            "selection_sha256": module.canonical_hash(value),
            "project_id": project["id"],
            "snapshot_sha256": snapshots[project["id"]],
            "source_annotation_sha256": {
                slot["id"]: raw_hashes[f"{slot['id']}/{project['id']}.json"]
                for slot in value["annotator_slots"]
            },
            "adjudicator_id": "independent-human-adjudicator",
            "gold_frozen": True,
            "adjudication_attestation": {
                "human_adjudicator": True,
                "independent_of_annotators": True,
                "condition_blinded": True,
                "no_agent_outputs_reviewed": True,
                "attested_at": "2026-08-09T02:00:00Z",
            },
            "element_inventory": [
                {
                    "element_id": f"{project['id']}-readme",
                    "component_id": "project_documentation",
                    "path": "README.md",
                    "element_type": "document",
                    "observed_state": "inspected",
                }
            ],
            "gold_findings": [],
            "adjudication_notes": "Synthetic no-finding resolution.",
        }
        path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")


class NaturalProjectLabelFreezeTests(unittest.TestCase):
    def test_freeze_labels_rejects_incomplete_project_slot_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module, _, run_dir = prepare_run(Path(temporary))

            with self.assertRaisesRegex(module.ContractError, "missing independent annotation"):
                module.freeze_labels(run_dir)

    def test_freeze_labels_binds_raw_labels_gold_and_gate_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module, value, run_dir = prepare_run(Path(temporary))
            raw_hashes = write_completed_annotations(module, value, run_dir)
            write_adjudicated_gold(module, value, run_dir, raw_hashes)

            result = module.freeze_labels(run_dir)
            commitment_path = run_dir / "review" / "label_commitment.json"
            commitment = json.loads(commitment_path.read_text(encoding="utf-8"))
            self.assertEqual(result["commitment_state"], "frozen")
            self.assertEqual(commitment["annotation_count"], 8)
            self.assertEqual(commitment["project_count"], 4)
            self.assertEqual(commitment["raw_label_sha256"], raw_hashes)
            self.assertEqual(len(commitment["adjudicated_gold_sha256"]), 4)
            self.assertRegex(commitment["label_set_sha256"], r"^[0-9a-f]{64}$")

            gate = module.execution_gate_status(run_dir)
            self.assertEqual(gate["missing_gates"], ["two_live_agent_families"])

            tampered = run_dir / "review" / "raw_labels" / "human_a" / "python_signing.json"
            tampered.write_text(tampered.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            gate = module.execution_gate_status(run_dir)
            self.assertIn("invalid_label_commitment", gate["missing_gates"])
            self.assertIn("independent_human_labels", gate["missing_gates"])
            self.assertIn("blinded_adjudicated_gold", gate["missing_gates"])

    def test_gate_rejects_a_forged_summary_only_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            module, _, run_dir = prepare_run(Path(temporary))
            manifest = json.loads(
                (run_dir / "controller" / "selection_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            forged = {
                "selection_sha256": manifest["selection_sha256"],
                "independent_human_annotators": 2,
                "condition_blinded": True,
                "gold_frozen": True,
            }
            (run_dir / "review" / "label_commitment.json").write_text(
                json.dumps(forged), encoding="utf-8"
            )
            (run_dir / "protocol" / "live_agent_config.json").write_text(
                json.dumps(
                    {
                        "agent_families": [
                            {"id": "family-a", "kind": "live_agent", "version": "1"},
                            {"id": "family-b", "kind": "live_agent", "version": "1"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            gate = module.execution_gate_status(run_dir)
            self.assertEqual(gate["execution_state"], "blocked")
            self.assertIn("invalid_label_commitment", gate["missing_gates"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "evaluation" / "scripts"
PILOT_SCRIPT = SCRIPT_DIR / "natural_project_pilot.py"
PILOT_HELPERS = Path(__file__).with_name("test_natural_project_pilot.py")
LABEL_HELPERS = Path(__file__).with_name("test_natural_project_label_freeze.py")
CALIBRATION_HELPERS = Path(__file__).with_name("test_annotation_calibration_freeze.py")


def load_path(name: str, path: Path):
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPT_DIR))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_unbound_pilot(root: Path):
    module = load_path("natural_project_codebook_binding", PILOT_SCRIPT)
    helpers = load_path("natural_project_pilot_binding_helpers", PILOT_HELPERS)
    selection = helpers.selection()
    selection_path = root / "pilot-selection.json"
    selection_path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    snapshot_root = root / "pilot-snapshots"
    helpers.create_snapshots(snapshot_root, selection)
    prepared = module.prepare_annotation_workspace(selection_path, snapshot_root, root / "pilot-runs")
    return module, selection, Path(prepared["run_dir"])


class NaturalProjectCodebookBindingTests(unittest.TestCase):
    def test_labels_fail_closed_until_completed_calibration_is_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module, _, run_dir = prepare_unbound_pilot(root)
            calibration_helpers = load_path("completed_calibration_helpers", CALIBRATION_HELPERS)
            _, _, calibration_run, _, _ = calibration_helpers.complete_and_freeze_calibration(
                root / "calibration"
            )

            gate = module.execution_gate_status(run_dir)
            self.assertIn("frozen_annotation_codebook", gate["missing_gates"])
            with self.assertRaisesRegex(module.ContractError, "frozen annotation codebook"):
                module.label_preflight(run_dir)

            binding = module.bind_codebook(run_dir, calibration_run)
            self.assertEqual(binding["binding_state"], "frozen")
            self.assertTrue(binding["calibration_completed"])
            self.assertRegex(binding["study_codebook_binding_sha256"], r"^[0-9a-f]{64}$")
            frozen_codebook = run_dir / "protocol" / "frozen-annotation-codebook.md"
            self.assertEqual(binding["annotation_codebook_sha256"], sha256(frozen_codebook))

    def test_label_commitment_consumes_binding_and_tampering_blocks_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module, selection, run_dir = prepare_unbound_pilot(root)
            calibration_helpers = load_path("binding_calibration_helpers", CALIBRATION_HELPERS)
            _, _, calibration_run, _, calibration_commitment = (
                calibration_helpers.complete_and_freeze_calibration(root / "calibration")
            )
            binding = module.bind_codebook(run_dir, calibration_run)

            label_helpers = load_path("natural_label_binding_helpers", LABEL_HELPERS)
            raw_hashes = label_helpers.write_completed_annotations(module, selection, run_dir)
            label_helpers.write_adjudicated_gold(module, selection, run_dir, raw_hashes)
            label_commitment = module.freeze_labels(run_dir)

            self.assertEqual(
                label_commitment["annotation_codebook_sha256"],
                binding["annotation_codebook_sha256"],
            )
            self.assertEqual(
                label_commitment["calibration_set_sha256"],
                calibration_commitment["calibration_set_sha256"],
            )
            self.assertEqual(
                label_commitment["study_codebook_binding_sha256"],
                binding["study_codebook_binding_sha256"],
            )

            frozen_codebook = run_dir / "protocol" / "frozen-annotation-codebook.md"
            frozen_codebook.write_text(
                frozen_codebook.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            gate = module.execution_gate_status(run_dir)
            self.assertIn("invalid_codebook_commitment", gate["missing_gates"])
            self.assertIn("frozen_annotation_codebook", gate["missing_gates"])

    def test_binding_rejects_incomplete_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module, _, run_dir = prepare_unbound_pilot(root)
            calibration_helpers = load_path("pending_calibration_helpers", CALIBRATION_HELPERS)
            _, _, calibration_run, _ = calibration_helpers.prepare_calibration_run(
                root / "calibration"
            )
            with self.assertRaisesRegex(module.ContractError, "calibration commitment"):
                module.bind_codebook(run_dir, calibration_run)


if __name__ == "__main__":
    unittest.main()

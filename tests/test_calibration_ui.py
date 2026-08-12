from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "evaluation" / "scripts" / "calibration_ui.py"
FRONTEND = ROOT / "evaluation" / "ui" / "calibration-console.html"
CALIBRATION_HELPERS = Path(__file__).with_name("test_annotation_calibration_freeze.py")
PILOT_HELPERS = Path(__file__).with_name("test_natural_project_pilot.py")
NATURAL_SCRIPT = ROOT / "evaluation" / "scripts" / "natural_project_pilot.py"


def load_path(name: str, path: Path):
    script_dir = str(path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed_payload(run_dir: Path, slot_id: str, annotator_id: str) -> dict:
    packet = next((run_dir / "annotation_packets" / slot_id).glob("*/annotation.template.json"))
    payload = json.loads(packet.read_text(encoding="utf-8"))
    payload.update(
        {
            "annotator_id": annotator_id,
            "completed": True,
            "human_attestation": {
                "human_annotator": True,
                "independent": True,
                "condition_blinded": True,
                "no_agent_outputs_reviewed": True,
                "attested_at": "2026-08-10T04:00:00Z",
            },
            "element_inventory": [
                {
                    "element_id": f"{slot_id}-readme",
                    "component_id": "project_documentation",
                    "path": "README.md",
                    "element_type": "document",
                    "observed_state": "inspected",
                }
            ],
            "candidate_findings": [],
            "notes": "Synthetic UI contract fixture; no finding recorded.",
        }
    )
    return payload


def prepare_unbound_pilot(root: Path) -> Path:
    natural = load_path("calibration_ui_natural", NATURAL_SCRIPT)
    helpers = load_path("calibration_ui_pilot_helpers", PILOT_HELPERS)
    selection = helpers.selection()
    selection_path = root / "pilot-selection.json"
    selection_path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    snapshots = root / "pilot-snapshots"
    helpers.create_snapshots(snapshots, selection)
    result = natural.prepare_annotation_workspace(selection_path, snapshots, root / "pilot-runs")
    return Path(result["run_dir"])


class CalibrationUITests(unittest.TestCase):
    def prepare(self, root: Path, *, with_pilot: bool = False):
        helpers = load_path("calibration_ui_calibration_helpers", CALIBRATION_HELPERS)
        _, _, run_dir, codebook = helpers.prepare_calibration_run(root / "calibration")
        pilot = prepare_unbound_pilot(root) if with_pilot else None
        ui = load_path("calibration_ui", SCRIPT)
        service = ui.CalibrationUIService(
            run_dir,
            pilot_run_dir=pilot,
            role_tokens={
                "coordinator": "coordinator-token",
                "human_calibrator_a": "human-a-token",
                "human_calibrator_b": "human-b-token",
            },
        )
        return ui, service, run_dir, codebook, pilot

    def test_annotator_views_are_isolated_and_source_paths_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ui, service, _, _, _ = self.prepare(Path(temporary))

            state = service.state("human-a-token")
            self.assertEqual(state["role"], "annotator")
            self.assertEqual(state["slot_id"], "human_calibrator_a")
            self.assertNotIn("human_calibrator_b", json.dumps(state))
            self.assertEqual(
                service.annotation("human-a-token")["annotator_slot_id"],
                "human_calibrator_a",
            )
            with self.assertRaisesRegex(ui.UIContractError, "not available"):
                service.annotation("coordinator-token")
            with self.assertRaisesRegex(ui.UIContractError, "unsafe source path"):
                service.source_text("human-a-token", "../packet_manifest.json")
            with self.assertRaisesRegex(ui.UIContractError, "invalid role token"):
                service.state("wrong-token")

    def test_two_final_submissions_unlock_discussion_without_allowing_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ui, service, run_dir, _, _ = self.prepare(Path(temporary))
            first = completed_payload(run_dir, "human_calibrator_a", "human-one")
            second = completed_payload(run_dir, "human_calibrator_b", "human-two")

            saved = service.submit_annotation("human-a-token", first)
            self.assertEqual(saved["submission_state"], "committed")
            self.assertFalse(service.state("coordinator-token")["discussion_enabled"])
            changed = dict(first)
            changed["notes"] = "A forbidden rewrite."
            with self.assertRaisesRegex(ui.UIContractError, "already committed"):
                service.submit_annotation("human-a-token", changed)

            service.submit_annotation("human-b-token", second)
            coordinator = service.state("coordinator-token")
            self.assertEqual(len(coordinator["annotator_access"]), 2)
            self.assertTrue(
                all(row["fragment"].startswith("#token=") for row in coordinator["annotator_access"])
            )
            self.assertTrue(coordinator["discussion_enabled"])
            context = service.discussion_context("coordinator-token")
            self.assertEqual(set(context["annotations"]), {"human_calibrator_a", "human_calibrator_b"})

    def test_coordinator_can_freeze_then_bind_but_cannot_skip_human_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ui, service, run_dir, codebook, pilot = self.prepare(
                Path(temporary), with_pilot=True
            )
            with self.assertRaisesRegex(ui.UIContractError, "missing calibration annotation"):
                service.freeze_calibration(
                    "coordinator-token",
                    final_codebook=codebook.read_text(encoding="utf-8"),
                    disagreement_items=[],
                    codebook_decisions=[],
                )

            service.submit_annotation(
                "human-a-token",
                completed_payload(run_dir, "human_calibrator_a", "human-one"),
            )
            service.submit_annotation(
                "human-b-token",
                completed_payload(run_dir, "human_calibrator_b", "human-two"),
            )
            frozen = service.freeze_calibration(
                "coordinator-token",
                final_codebook=codebook.read_text(encoding="utf-8"),
                disagreement_items=[],
                codebook_decisions=[],
            )
            self.assertEqual(frozen["commitment_state"], "frozen")
            self.assertEqual(service.state("coordinator-token")["calibration_state"], "complete")

            binding = service.bind_study("coordinator-token")
            self.assertEqual(binding["binding_state"], "frozen")
            self.assertTrue((pilot / "protocol" / "codebook_commitment.json").is_file())
            gate = service.pilot_gate("coordinator-token")
            self.assertNotIn("frozen_annotation_codebook", gate["missing_gates"])

    def test_http_server_serves_the_page_and_requires_a_role_token_for_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ui, service, _, _, _ = self.prepare(Path(temporary))
            server = ui.create_server(service, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address[:2]
            try:
                with urllib.request.urlopen(f"http://{host}:{port}/") as response:
                    self.assertIn("Calibration Console", response.read().decode("utf-8"))
                request = urllib.request.Request(
                    f"http://{host}:{port}/api/state",
                    headers={"Authorization": "Bearer human-a-token"},
                )
                with urllib.request.urlopen(request) as response:
                    state = json.loads(response.read().decode("utf-8"))
                self.assertEqual(state["slot_id"], "human_calibrator_a")
                denied = urllib.request.Request(
                    f"http://{host}:{port}/api/state",
                    headers={"Authorization": "Bearer wrong-token"},
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(denied)
                self.assertEqual(raised.exception.code, 409)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_frontend_is_offline_accessible_and_exposes_the_three_phase_workflow(self) -> None:
        page = FRONTEND.read_text(encoding="utf-8")
        self.assertIn("<main", page)
        self.assertIn('aria-label="Calibration phases"', page)
        self.assertIn("Independent annotation", page)
        self.assertIn("Compare &amp; discuss", page)
        self.assertIn("Freeze &amp; bind", page)
        self.assertIn("prefers-color-scheme: dark", page)
        self.assertIn("prefers-reduced-motion", page)
        self.assertIn("min-height: 44px", page)
        self.assertNotIn("https://", page)
        self.assertNotIn("http://", page)


if __name__ == "__main__":
    unittest.main()

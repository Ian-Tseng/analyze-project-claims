from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from nomination_contract_support import canonical, digest, load
from nomination_runtime_fixtures import refresh_claim_record, refresh_component_map

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "contracts/evidence-nomination/v1/golden"
CLI = ROOT / "scripts/evidence_nomination.py"
SKILL = ROOT / "skills/analyze-project-claims"


class NominationCompileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nomination-compile-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve() / "project"
        shutil.copytree(GOLDEN / "project", self.project)
        self.output = self.project / ".analyze-project-claims/nominations"
        self.request = refresh_component_map(self.project, load(GOLDEN / "gap-request.json"))
        self.map_before = (self.project / "map/accepted-map.json").read_bytes()

    def cli(self, command, *args, expected=0):
        result = subprocess.run([sys.executable, "-I", str(CLI), command, *map(str,args), "--format", "json"],
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt["network"])
        self.assertFalse(receipt["accepted_state_changed"])
        return receipt

    def scope(self):
        args = ["--project-root", self.project, "--map-root", self.project / "map"]
        if self.request["target"]["kind"] == "claim":
            args += ["--record", self.project / "record.json"]
        return args

    def prepare(self):
        request_path = self.project / "request.json"
        request_path.write_bytes(canonical(self.request) + b"\n")
        result = self.cli("nominate", "--request", request_path, "--out-dir", self.output, *self.scope())
        self.bundle_path = Path(result["artifact_path"])
        self.bundle = load(self.bundle_path)
        self.selection_path = Path(result["selection_path"])
        self.candidate_path = self.output / "review.candidate.json"
        self.selection = load(GOLDEN / ("claim-selection.json" if self.request["target"]["kind"] == "claim" else "selection.json"))
        self.selection["bundle"] = load(self.selection_path)["bundle"]
        self.save_selection()

    def save_selection(self):
        self.selection_path.write_bytes(canonical(self.selection) + b"\n")

    def compile(self, expected=0):
        return self.cli("compile", "--bundle", self.bundle_path, "--selection", self.selection_path,
                        "--output", self.candidate_path, *self.scope(), expected=expected)

    def test_component_compiles_only_reviewed_locators_without_authority_writes(self):
        self.prepare()
        result = self.compile()
        candidate = load(self.candidate_path)
        self.assertEqual(candidate["payload"], load(GOLDEN / "component-candidate.json")["payload"])
        self.assertEqual(candidate["provenance"]["selection_sha256"], hashlib.sha256(self.selection_path.read_bytes()).hexdigest())
        self.assertEqual(result["next_command"][0], "handoff")
        self.assertEqual((self.project / "map/accepted-map.json").read_bytes(), self.map_before)
        self.assertEqual(list((self.project / "map").iterdir()), [self.project / "map/accepted-map.json"])

    def use_claim(self):
        self.request = refresh_claim_record(self.project, load(GOLDEN / "claim-gap-request.json"))

    def handoff(self, expected=0):
        return self.cli("handoff", "--candidate", self.candidate_path, "--bundle", self.bundle_path,
                        "--selection", self.selection_path, "--output", self.output / "native.payload.json",
                        *self.scope(), expected=expected)

    def native(self, argv, expected=0):
        result = subprocess.run([sys.executable, *map(str, argv)], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_claim_payload_is_reviewer_authored_and_native_validate_accepts_handoff(self):
        self.use_claim(); self.prepare(); self.compile()
        candidate = load(self.candidate_path)
        self.assertEqual(candidate["payload"], self.selection["reviewer_input"]["record_input"])
        result = self.handoff()
        native = self.native(result["next_command"])
        self.assertEqual(json.loads(native.stdout)["status"], "valid")
        self.assertEqual((self.project / "map/accepted-map.json").read_bytes(), self.map_before)
        self.assertFalse((self.project / "validation").exists())

    def test_component_handoff_reconciles_candidate_without_accepting(self):
        self.prepare(); self.compile()
        result = self.handoff()
        self.assertEqual(list((self.project / "map").iterdir()), [self.project / "map/accepted-map.json"])
        native = self.native(result["next_command"])
        self.assertIsNotNone(json.loads(native.stdout)["candidate"])
        self.assertEqual((self.project / "map/accepted-map.json").read_bytes(), self.map_before)

    def test_draft_and_incomplete_selection_refused(self):
        self.prepare()
        original = copy.deepcopy(self.selection)
        for field, value in (("selections", []), ("reviewer_input", None)):
            self.selection = copy.deepcopy(original); self.selection[field] = value; self.save_selection()
            self.assertEqual(self.compile(expected=2)["code"], "selection_incomplete")
            self.assertFalse(self.candidate_path.exists())

    def test_selection_requires_unique_existing_ids_and_matching_kind(self):
        self.prepare()
        original = copy.deepcopy(self.selection)
        self.selection["selections"] *= 2; self.save_selection(); self.compile(expected=2)
        self.selection = copy.deepcopy(original)
        self.selection["selections"][0]["nomination_id"] = "hit-" + "0" * 64
        self.save_selection(); self.compile(expected=2)
        self.selection = copy.deepcopy(original)
        self.selection["reviewer_input"] = load(GOLDEN / "claim-selection.json")["reviewer_input"]
        self.save_selection(); self.compile(expected=2)
        self.assertFalse(self.candidate_path.exists())

    def test_claim_selected_evidence_and_explicit_role_are_exact(self):
        self.use_claim(); self.prepare()
        original = copy.deepcopy(self.selection)
        changes = [("source", {"kind":"file", "path":"evidence/counter.txt"}),
                   ("locator", {"kind":"line_range", "start":1, "end":2}),
                   ("method", "inferred"), ("observed_summary", "An invented observation.")]
        for field, value in changes:
            self.selection = copy.deepcopy(original)
            self.selection["reviewer_input"]["record_input"]["evidence_items"][0][field] = value
            self.save_selection(); self.compile(expected=2)
        self.selection = copy.deepcopy(original)
        self.selection["selections"][0]["evidence_role"] = "contradicts"
        self.save_selection(); self.compile(expected=2)
        self.selection = copy.deepcopy(original)
        del self.selection["selections"][0]["evidence_id"]
        self.save_selection(); self.compile(expected=2)
        self.assertFalse(self.candidate_path.exists())

    def test_claim_target_statement_and_reference_cannot_change(self):
        self.use_claim(); self.prepare()
        original = copy.deepcopy(self.selection)
        for field, value in (("claim_id", "other-claim"), ("statement", "Changed claim."),
                             ("element_ref", {"component_id":"results", "element_id":"other"})):
            self.selection = copy.deepcopy(original)
            self.selection["reviewer_input"]["record_input"]["claims"][0][field] = value
            self.save_selection(); self.compile(expected=2)
        self.assertFalse(self.candidate_path.exists())

    def test_component_preserves_reviewer_fields_and_conflicting_evidence(self):
        self.prepare()
        observation = self.selection["reviewer_input"]["observation"]
        element = observation["components"][0]["elements"][0]
        extra = {"source":"evidence/support.txt", "locator":"lines:1-1", "observed":"Conflicting reviewer note."}
        element["evidence"].append(extra)
        self.save_selection(); self.compile()
        expected = copy.deepcopy(observation)
        expected["components"][0]["elements"][0]["evidence"].append({"source":"evidence/support.txt", "locator":"lines:1-1", "observed":self.selection["selections"][0]["observed_summary"]})
        self.assertEqual(load(self.candidate_path)["payload"], expected)

    def test_component_exact_evidence_deduplicates(self):
        self.prepare()
        observation = self.selection["reviewer_input"]["observation"]
        observation["components"][0]["elements"][0]["evidence"].append({"source":"evidence/support.txt", "locator":"lines:1-1", "observed":self.selection["selections"][0]["observed_summary"]})
        self.save_selection(); self.compile()
        self.assertEqual(load(self.candidate_path)["payload"], observation)

    def test_component_rejects_added_removed_retargeted_or_retyped_structure(self):
        self.prepare()
        original = copy.deepcopy(self.selection)
        self.selection["reviewer_input"]["observation"]["components"][0]["component_type"] = "method"
        self.save_selection(); self.compile(expected=2)
        self.selection = copy.deepcopy(original)
        self.selection["reviewer_input"]["observation"]["components"][0]["elements"][0]["target"] = "other target"
        self.save_selection(); self.compile(expected=2)
        self.selection = copy.deepcopy(original)
        elements = self.selection["reviewer_input"]["observation"]["components"][0]["elements"]
        other = copy.deepcopy(elements[0]); other["element_id"] = "other"; elements.append(other)
        self.save_selection(); self.compile(expected=2)
        self.selection = copy.deepcopy(original)
        self.selection["reviewer_input"]["observation"]["components"] = []
        self.save_selection(); self.compile(expected=2)
        self.selection = copy.deepcopy(original)
        self.selection["selections"][0]["evidence_id"] = "unexpected"
        self.save_selection(); self.compile(expected=2)
        self.assertFalse(self.candidate_path.exists())

    def test_source_changes_refuse_compile_without_output(self):
        self.prepare()
        (self.project / "evidence/support.txt").write_bytes(b"Metric accuracy is 0.40.\n")
        self.compile(expected=4)
        self.assertFalse(self.candidate_path.exists())

    def test_reformatted_bundle_invalidates_raw_selection_binding(self):
        self.prepare()
        self.bundle_path.write_text(json.dumps(self.bundle, indent=2), encoding="utf-8")
        self.compile(expected=4)
        self.assertFalse(self.candidate_path.exists())

    def test_compile_no_clobber_and_raw_selection_identity(self):
        self.prepare(); self.compile()
        before = self.candidate_path.read_bytes()
        self.assertEqual(self.compile()["code"], "reused_identical")
        self.selection_path.write_text(json.dumps(self.selection, indent=2), encoding="utf-8")
        self.compile(expected=5)
        self.assertEqual(self.candidate_path.read_bytes(), before)
        self.candidate_path = self.output / "reformatted.candidate.json"
        self.compile()
        self.assertNotEqual(load(self.candidate_path)["candidate_id"], json.loads(before)["candidate_id"])

    def test_handoff_replays_provenance_even_after_rehashing_tampered_candidate(self):
        self.prepare(); self.compile()
        candidate = load(self.candidate_path)
        candidate["payload"]["objective"] = "Tampered objective."
        identity = digest({k:v for k,v in candidate.items() if k not in ("candidate_id", "canonical_payload_sha256")})
        candidate.update(candidate_id="candidate-"+identity, canonical_payload_sha256=identity)
        self.candidate_path.write_bytes(canonical(candidate)+b"\n")
        self.handoff(expected=4)
        self.assertFalse((self.output / "native.payload.json").exists())

    def test_handoff_refuses_selection_byte_drift(self):
        self.prepare(); self.compile()
        self.selection_path.write_text(json.dumps(self.selection, indent=2), encoding="utf-8")
        self.handoff(expected=4)
        self.assertFalse((self.output / "native.payload.json").exists())

    def test_handoff_refuses_source_drift(self):
        self.prepare(); self.compile()
        (self.project / "evidence/support.txt").write_bytes(b"Metric accuracy is 0.40.\n")
        self.handoff(expected=4)
        self.assertFalse((self.output / "native.payload.json").exists())

    def test_output_cannot_enter_authority_or_search_inputs(self):
        self.prepare()
        for path in (self.project / "validation/candidate.json", self.project / "map/candidate.json",
                     self.project / "evidence/candidate.json", self.selection_path, self.bundle_path):
            self.candidate_path = path
            self.compile(expected=2)
        self.assertFalse((self.project / "validation").exists())

    def test_native_triple_guards_each_reject_before_validate_append_or_reconcile(self):
        for kind in ("component", "claim"):
            if kind == "claim":
                self.use_claim()
            self.prepare(); self.candidate_path = self.output / (kind+".candidate.json"); self.compile()
            # Distinct native payload output avoids intentional no-clobber conflicts.
            handoff = self.cli("handoff", "--candidate", self.candidate_path, "--bundle", self.bundle_path,
                               "--selection", self.selection_path, "--output", self.output / (kind+".payload.json"), *self.scope())
            argv = handoff["next_command"]
            before = {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
            commands = [argv]
            if kind == "claim":
                append = list(argv); append[1] = "append"; append += ["--log-dir", str(self.project / "validation/history")]
                commands.append(append)
            for command in commands:
                for flag, wrong in (("--expected-map-id", "component-map-"+"0"*12),
                                    ("--expected-map-canonical-sha256", "0"*64), ("--expected-map-file-sha256", "0"*64)):
                    bad = list(command); bad[bad.index(flag)+1] = wrong
                    self.assertIn("EXPECTED_MAP_MISMATCH", self.native(bad, expected=2).stderr)
                bad = list(command); offset = bad.index("--expected-map-id"); del bad[offset:offset+2]
                self.assertIn("EXPECTED_MAP_INVALID", self.native(bad, expected=2).stderr)
            after = {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
            self.assertEqual(before, after)

    def test_native_raw_map_drift_and_payload_edit_reject_after_handoff(self):
        self.use_claim(); self.prepare(); self.compile()
        argv = self.handoff()["next_command"]
        map_path = self.project / "map/accepted-map.json"
        map_path.write_text(json.dumps(json.loads(self.map_before), indent=2), encoding="utf-8")
        self.assertIn("EXPECTED_MAP_MISMATCH", self.native(argv, expected=2).stderr)
        map_path.write_bytes(self.map_before)
        payload_path = self.output / "native.payload.json"
        payload_path.write_bytes(payload_path.read_bytes()+b" ")
        self.assertIn("EXPECTED_INPUT_MISMATCH", self.native(argv, expected=2).stderr)
        self.assertFalse((self.project / "validation").exists())

    def test_guarded_native_append_is_separate_and_requires_explicit_invocation(self):
        self.use_claim(); self.prepare(); self.compile()
        argv = self.handoff()["next_command"]
        history = self.project / "validation/history"
        self.assertFalse(history.exists())
        argv[1] = "append"; argv += ["--log-dir", str(history)]
        self.assertEqual(json.loads(self.native(argv).stdout)["status"], "appended")
        self.assertEqual(len(list(history.glob("*.json"))), 1)
        self.assertEqual((self.project / "map/accepted-map.json").read_bytes(), self.map_before)

    def test_compile_and_handoff_do_not_execute_or_connect(self):
        self.prepare()
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts")))
        from _nomination.cli import parser, run
        base = ["--bundle", str(self.bundle_path), "--selection", str(self.selection_path), *map(str, self.scope())]
        with patch("subprocess.Popen", side_effect=AssertionError("process execution")), \
             patch("os.system", side_effect=AssertionError("shell execution")), \
             patch("socket.socket", side_effect=AssertionError("network connection")):
            run(parser().parse_args(["compile", *base, "--output", str(self.candidate_path)]))
            run(parser().parse_args(["handoff", *base, "--candidate", str(self.candidate_path),
                                     "--output", str(self.output / "native.payload.json")]))
        self.assertEqual(list((self.project / "map").iterdir()), [self.project / "map/accepted-map.json"])

    def test_native_append_rechecks_map_after_materializing_evidence(self):
        self.use_claim(); self.prepare(); self.compile()
        argv = self.handoff()["next_command"]
        sys.path.insert(0, str(SKILL / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(SKILL / "scripts")))
        from _internal import evidence_bound_scan as recorder
        from _internal.component_evidence.map_guard import MapGuardError
        argv[1] = "append"; argv += ["--log-dir", str(self.project / "validation/history")]
        args = recorder._parser().parse_args(argv[1:])
        original = recorder._build_record
        def changing_map(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.project / "map/accepted-map.json").write_bytes(self.map_before + b" ")
            return result
        with patch.object(recorder, "_build_record", side_effect=changing_map):
            with self.assertRaisesRegex(MapGuardError, "EXPECTED_MAP_MISMATCH"):
                recorder._append(args, SKILL)
        self.assertFalse((self.project / "validation/history").exists())

    def test_missing_map_cannot_bootstrap_through_guarded_reconcile(self):
        self.prepare(); self.compile()
        argv = self.handoff()["next_command"]
        map_path = self.project / "map/accepted-map.json"
        map_path.unlink()  # Test-owned fixture only.
        self.assertIn("GUARDED_INPUT_INVALID", self.native(argv, expected=2).stderr)
        self.assertEqual(list(map_path.parent.iterdir()), [])

    def test_historical_claim_record_is_refused_without_rewriting_it(self):
        self.request = load(GOLDEN / "claim-gap-request.json")
        request_path = self.project / "request.json"
        request_path.write_bytes(canonical(self.request)+b"\n")
        before = (self.project / "record.json").read_bytes()
        result = self.cli("nominate", "--request", request_path, "--out-dir", self.output, *self.scope(), expected=4)
        self.assertEqual(result["code"], "stale_identity")
        self.assertEqual((self.project / "record.json").read_bytes(), before)
        self.assertFalse(self.output.exists())

    def test_native_entry_code_drift_invalidates_handoff(self):
        self.prepare(); self.compile()
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts")))
        from _nomination import engine
        from _nomination.compiler import handoff
        from _nomination.common import Failure
        original = engine.safe_read
        def drifted(path, *args, **kwargs):
            raw = original(path, *args, **kwargs)
            if Path(path) == SKILL / "scripts/record_scan.py":
                return raw + b"\n# changed native entry\n"
            return raw
        with patch.object(engine, "safe_read", side_effect=drifted):
            with self.assertRaises(Failure) as caught:
                handoff(self.candidate_path, self.bundle_path, self.selection_path, self.project, self.project / "map")
        self.assertEqual(caught.exception.code, "stale_identity")
        self.assertFalse((self.output / "native.payload.json").exists())

    def test_guarded_record_retains_native_five_mib_input_limit(self):
        self.use_claim(); self.prepare(); self.compile()
        argv = self.handoff()["next_command"]
        path = self.output / "native.payload.json"
        raw = path.read_bytes().ljust(5 * 1024 * 1024 + 1, b" ")
        path.write_bytes(raw)
        argv[argv.index("--expected-input-sha256")+1] = hashlib.sha256(raw).hexdigest()
        self.assertIn("GUARDED_INPUT_INVALID", self.native(argv, expected=2).stderr)

    def test_guarded_record_retains_native_five_mib_map_limit(self):
        self.use_claim(); self.prepare(); self.compile()
        argv = self.handoff()["next_command"]
        path = self.project / "map/accepted-map.json"
        raw = path.read_bytes().ljust(5 * 1024 * 1024 + 1, b" ")
        path.write_bytes(raw)
        argv[argv.index("--expected-map-file-sha256")+1] = hashlib.sha256(raw).hexdigest()
        self.assertIn("GUARDED_INPUT_INVALID", self.native(argv, expected=2).stderr)


if __name__ == "__main__":
    unittest.main()

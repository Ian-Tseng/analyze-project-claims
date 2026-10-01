"""Exercise the checked-in public example through fresh isolated commands."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/evidence-nomination/minimal"
CLI = ROOT / "scripts/evidence_nomination.py"

class NominationJourneyTests(unittest.TestCase):
    def run_command(self, script, *args, expected=0, isolated=True):
        result = subprocess.run([sys.executable, *(["-I"] if isolated else []), str(script), *map(str, args)],
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_public_example_reaches_native_candidate_and_preserves_authority(self):
        with tempfile.TemporaryDirectory(prefix="nomination-journey-") as temp:
            run_root = Path(temp).resolve() / "fresh-example"
            prepared = self.run_command(EXAMPLE / "setup_project.py", "--output", run_root)
            project = Path(prepared["project_root"])
            request = Path(prepared["request"])
            before = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob("*") if p.is_file()}
            scope = ["--project-root", project, "--map-root", project / "map", "--format", "json"]
            output = project / ".analyze-project-claims/nominations"
            nominated = self.run_command(CLI, "nominate", "--request", request, "--out-dir", output, *scope)
            bundle = Path(nominated["artifact_path"])
            shown = self.run_command(CLI, "show", "--bundle", bundle, "--format", "json")
            self.assertEqual(shown["nomination_count"], 3)
            reused = self.run_command(CLI, "nominate", "--request", request, "--out-dir", output, *scope)
            self.assertEqual(reused["code"], "reused_identical")
            selection = output / "reviewed.selection.json"
            self.run_command(EXAMPLE / "prepare_selection.py", "--bundle", bundle, "--output", selection)
            candidate = output / "component.candidate.json"
            self.run_command(CLI, "compile", "--bundle", bundle, "--selection", selection, "--output", candidate, *scope)
            self.assertEqual(json.loads(candidate.read_bytes())["payload"], json.loads((EXAMPLE / "expected-observation.json").read_bytes()))
            handoff = self.run_command(CLI, "handoff", "--bundle", bundle, "--selection", selection, "--candidate", candidate, "--output", output / "native.payload.json", *scope)
            command = handoff["next_command"]
            native = self.run_command(command[0], *command[1:], isolated=False)
            self.assertIsNotNone(native["candidate"])
            for name, raw in before.items():
                self.assertEqual((project / name).read_bytes(), raw, name)
            self.assertFalse((project / "validation").exists())
            self.run_command(CLI, "verify", "--bundle", bundle, *scope)
            (project / "evidence/support.txt").write_bytes(b"Changed source.\n")
            stale = self.run_command(CLI, "verify", "--bundle", bundle, *scope, expected=4)
            self.assertEqual(stale["code"], "stale_identity")

    def test_synthetic_setup_preserves_history_and_refuses_existing_or_source_output(self):
        with tempfile.TemporaryDirectory(prefix="nomination-setup-") as temp:
            output = Path(temp).resolve() / "fresh"
            historical = {p: p.read_bytes() for p in EXAMPLE.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
            self.run_command(EXAMPLE / "setup_project.py", "--output", output)
            prepared = {p: p.read_bytes() for p in output.rglob("*") if p.is_file()}
            self.run_command(EXAMPLE / "setup_project.py", "--output", output, expected=2)
            self.run_command(EXAMPLE / "setup_project.py", "--output", EXAMPLE / "forbidden-output", expected=2)
            self.assertFalse((EXAMPLE / "forbidden-output").exists())
            for path, raw in prepared.items():
                self.assertEqual(path.read_bytes(), raw)
            for path, raw in historical.items():
                self.assertEqual(path.read_bytes(), raw)

    def test_prerecorded_review_rejects_unrecognized_map_identity(self):
        with tempfile.TemporaryDirectory(prefix="nomination-map-review-") as temp:
            root = Path(temp).resolve()
            bundle = root / "bundle.json"
            value = json.loads((EXAMPLE / "golden/bundle.json").read_bytes())
            value["request"]["map"]["file_sha256"] = "0" * 64
            bundle.write_text(json.dumps(value), encoding="utf-8")
            output = root / "reviewed.json"
            self.run_command(EXAMPLE / "prepare_selection.py", "--bundle", bundle, "--output", output, expected=2)
            self.assertFalse(output.exists())

    def test_prerecorded_review_refuses_a_different_example_and_no_clobber(self):
        with tempfile.TemporaryDirectory(prefix="nomination-review-") as temp:
            root = Path(temp).resolve()
            bundle = root / "bundle.json"
            output = root / "reviewed.json"
            bundle.write_bytes((EXAMPLE / "golden/bundle.json").read_bytes())
            self.run_command(EXAMPLE / "prepare_selection.py", "--bundle", bundle, "--output", output)
            original = output.read_bytes()
            self.run_command(EXAMPLE / "prepare_selection.py", "--bundle", bundle, "--output", output, expected=2)
            self.assertEqual(output.read_bytes(), original)
            value = json.loads(bundle.read_bytes())
            value["nominations"][0]["excerpt"] = "Different evidence."
            bundle.write_text(json.dumps(value), encoding="utf-8")
            self.run_command(EXAMPLE / "prepare_selection.py", "--bundle", bundle, "--output", root / "other.json", expected=2)
            self.assertFalse((root / "other.json").exists())

if __name__ == "__main__":
    unittest.main()

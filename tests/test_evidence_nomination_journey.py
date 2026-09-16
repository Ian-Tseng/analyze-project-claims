"""Exercise the checked-in public example through fresh isolated commands."""
import json
import shutil
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
            project = Path(temp).resolve() / "project"
            shutil.copytree(EXAMPLE / "project", project)
            before = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob("*") if p.is_file()}
            scope = ["--project-root", project, "--map-root", project / "map", "--format", "json"]
            output = project / ".analyze-project-claims/nominations"
            nominated = self.run_command(CLI, "nominate", "--request", EXAMPLE / "request.json", "--out-dir", output, *scope)
            bundle = Path(nominated["artifact_path"])
            shown = self.run_command(CLI, "show", "--bundle", bundle, "--format", "json")
            self.assertEqual(shown["nomination_count"], 3)
            reused = self.run_command(CLI, "nominate", "--request", EXAMPLE / "request.json", "--out-dir", output, *scope)
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

"""Package-only execution must not depend on a publisher checkout."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nomination_runtime_fixtures import refresh_component_map

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/analyze-project-claims"
GOLDEN = ROOT / "contracts/evidence-nomination/v1/golden"

class NominationPackageTests(unittest.TestCase):
    def test_copied_package_runs_without_repository_contracts_or_modules(self):
        with tempfile.TemporaryDirectory(prefix="nomination-package-") as temp:
            base = Path(temp).resolve()
            package = base / "skill"
            shutil.copytree(SKILL, package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            project = base / "project"
            shutil.copytree(GOLDEN / "project", project)
            request = base / "request.json"
            request.write_text(json.dumps(refresh_component_map(project, json.loads((GOLDEN / "gap-request.json").read_bytes()))), encoding="utf-8")
            blobs = []
            for label, cli in (("checkout", ROOT / "scripts/evidence_nomination.py"),
                               ("copied", package / "scripts/evidence_nomination.py")):
                result = subprocess.run([sys.executable, "-I", str(cli), "nominate", "--request", str(request),
                    "--project-root", str(project), "--map-root", str(project / "map"),
                    "--out-dir", str(project / label), "--format", "json"],
                    cwd=base, capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                receipt = json.loads(result.stdout)
                blobs.append(Path(receipt["artifact_path"]).read_bytes())
                self.assertTrue((package / receipt["documentation"]).is_file())
            self.assertEqual(blobs[0], blobs[1])

    def test_packaged_contracts_preserve_bytes_except_native_ref_relocation(self):
        frozen = ROOT / "contracts/evidence-nomination/v1"
        packaged = SKILL / "references/evidence-nomination/v1"
        for source in [frozen / "CONTRACT.md", frozen / "policy.json", *frozen.glob("*.schema.json")]:
            expected = source.read_bytes().replace(b"../../../skills/analyze-project-claims/references/", b"../../")
            self.assertEqual((packaged / source.name).read_bytes(), expected)
        for source in (frozen / "templates").glob("*.json"):
            self.assertEqual((SKILL / "assets/evidence-nomination" / source.name).read_bytes(), source.read_bytes())

if __name__ == "__main__":
    unittest.main()

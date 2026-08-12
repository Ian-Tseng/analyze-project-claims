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
LOGGER = SKILL_ROOT / "scripts" / "record_scan.py"
EXAMPLE = ROOT / "examples" / "scan-input.example.json"


class RecordScanTests(unittest.TestCase):
    def run_scan(self, history: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(LOGGER),
                "--record",
                str(EXAMPLE),
                "--log-dir",
                str(history),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_scan_is_hierarchical_and_skill_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-scan-test-") as temp:
            history = Path(temp) / "history"
            result = self.run_scan(history)
            self.assertEqual(result.returncode, 0, result.stderr)
            paths = list(history.glob("*.json"))
            self.assertEqual(len(paths), 1)
            record = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertEqual(record["summary"]["scan_status"], "PARTIAL")
            self.assertEqual(record["summary"]["element_count"], 2)
            self.assertEqual(len(record["components"][0]["elements"]), 2)
            self.assertEqual(
                record["scan"]["skill_sha256"],
                hashlib.sha256((SKILL_ROOT / "SKILL.md").read_bytes()).hexdigest(),
            )

    def test_scans_are_append_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-scan-test-") as temp:
            history = Path(temp) / "history"
            first = self.run_scan(history)
            second = self.run_scan(history)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(len(list(history.glob("*.json"))), 2)

    def test_public_package_contract(self) -> None:
        self.assertFalse((ROOT / "skill").exists(), "Use the GitHub CLI-discoverable skills/ publisher layout.")
        required = [
            ROOT / "README.md",
            ROOT / "PUBLISHING.md",
            ROOT / "evaluation" / "README.md",
            ROOT / "VERSION",
            ROOT / "CITATION.cff.template",
            SKILL_ROOT / "SKILL.md",
            SKILL_ROOT / "agents" / "openai.yaml",
            SKILL_ROOT / "assets" / "component-map-observation.template.json",
            SKILL_ROOT / "assets" / "component-map.template.json",
            SKILL_ROOT / "assets" / "scan-record.template.json",
            SKILL_ROOT / "references" / "component-map-observation.schema.json",
            SKILL_ROOT / "references" / "component-map.schema.json",
            SKILL_ROOT / "references" / "scan-record.schema.json",
            SKILL_ROOT / "references" / "update-policy.schema.json",
            SKILL_ROOT / "references" / "package-version.json",
            SKILL_ROOT / "references" / "package-manifest.json",
            SKILL_ROOT / "scripts" / "update_policy.py",
            SKILL_ROOT / "scripts" / "reconcile_component_map.py",
            LOGGER,
            EXAMPLE,
            ROOT / "validation" / "README.md",
        ]
        self.assertEqual([str(path) for path in required if not path.is_file()], [])
        json.loads((SKILL_ROOT / "assets" / "scan-record.template.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "assets" / "component-map-observation.template.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "assets" / "component-map.template.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "scan-record.schema.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "component-map-observation.schema.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "component-map.schema.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "update-policy.schema.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "package-version.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "package-manifest.json").read_text(encoding="utf-8"))

    def test_documentation_identifies_observation_and_history_authority(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("component-map-observation.template.json", readme)
        self.assertIn("component-map-observation.schema.json", readme)
        self.assertIn("validation/README.md", readme)
        self.assertIn("[PUBLISHING.md](PUBLISHING.md)", readme)
        self.assertIn("[evaluation/README.md](evaluation/README.md)", readme)
        self.assertNotIn("## Upload and publish to GitHub", readme)
        self.assertNotIn("## Paper-facing evaluation plan", readme)
        self.assertNotIn("????", readme)
        self.assertLessEqual(len(readme.split()), 1200)
        self.assertLess(readme.index("## Install"), readme.index("## Quickstart"))
        publishing = (ROOT / "PUBLISHING.md").read_text(encoding="utf-8")
        self.assertIn("gh repo create", publishing)
        self.assertIn("gh skill publish .\\skills --dry-run", publishing)
        self.assertIn("gh skill update analyze-project-claims --dry-run", publishing)
        evaluation = (ROOT / "evaluation" / "README.md").read_text(encoding="utf-8")
        self.assertIn("## Claim-expansion plan", evaluation)
        authority = (ROOT / "validation" / "README.md").read_text(encoding="utf-8")
        self.assertIn("self-scan-input-v020.json", authority)
        self.assertIn("historical", authority.lower())
        self.assertIn("self-scan-input.json", authority)


if __name__ == "__main__":
    unittest.main()

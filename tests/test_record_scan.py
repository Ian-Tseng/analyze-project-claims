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
            ROOT / "CONTRIBUTING.md",
            ROOT / "SECURITY.md",
            ROOT / "LICENSE",
            ROOT / "evaluation" / "README.md",
            ROOT / "VERSION",
            ROOT / "CITATION.cff",
            SKILL_ROOT / "SKILL.md",
            SKILL_ROOT / "agents" / "openai.yaml",
            SKILL_ROOT / "assets" / "component-map-observation.template.json",
            SKILL_ROOT / "assets" / "component-map.template.json",
            SKILL_ROOT / "assets" / "scan-record.template.json",
            SKILL_ROOT / "references" / "component-map-observation.schema.json",
            SKILL_ROOT / "references" / "component-map.schema.json",
            SKILL_ROOT / "references" / "scan-record.schema.json",
            SKILL_ROOT / "references" / "problem-report.schema.json",
            SKILL_ROOT / "references" / "problem-report-policy.schema.json",
            SKILL_ROOT / "references" / "update-policy.schema.json",
            SKILL_ROOT / "references" / "package-version.json",
            SKILL_ROOT / "references" / "package-manifest.json",
            SKILL_ROOT / "scripts" / "update_policy.py",
            SKILL_ROOT / "scripts" / "reconcile_component_map.py",
            SKILL_ROOT / "scripts" / "problem_report.py",
            LOGGER,
            EXAMPLE,
            ROOT / "docs" / "PROBLEM_REPORTING.md",
            ROOT / "docs" / "MULTI_AGENT_SKILL_COMPATIBILITY_GUIDE.md",
            ROOT / "docs" / "CLAUDE_CODE_E2E_LOG.md",
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
        json.loads((SKILL_ROOT / "references" / "problem-report.schema.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "problem-report-policy.schema.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "package-version.json").read_text(encoding="utf-8"))
        json.loads((SKILL_ROOT / "references" / "package-manifest.json").read_text(encoding="utf-8"))
        self.assertFalse((ROOT / "CITATION.cff.template").exists())
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertIn(f'version: "{version}"', citation)
        self.assertIn('license: "MIT"', citation)
        self.assertNotIn("REPLACE_WITH_", citation)

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
        self.assertLessEqual(len(readme.split()), 1350)
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
        self.assertIn(
            "No separate active project check table is currently designated",
            authority,
        )
        self.assertNotIn("the active project check table", authority)

    def test_public_status_docs_are_scope_bound_and_release_claims_are_enforceable(self) -> None:
        review = (ROOT / "docs" / "PUBLIC_RELEASE_SECURITY_REVIEW.md").read_text(encoding="utf-8")
        self.assertIn("Pre-publication history-scan scope", review)
        self.assertIn("ending", review)
        self.assertIn("`65b995c57ef6a3b395fd995686add21aeb29fd01`", review)
        self.assertIn("Every release through `v0.6.0` (five releases)", review)
        self.assertNotIn("both `main` and `v0.6.0`", review)
        self.assertNotIn("Ten reachable commits", review)
        self.assertNotIn("Four published releases", review)

        e2e = (ROOT / "docs" / "PROBLEM_REPORTING_E2E_LOG.md").read_text(encoding="utf-8")
        self.assertIn("Historical status, superseded", e2e)
        self.assertIn("At the time of this E2E", e2e)
        self.assertNotIn("The repository remains private", e2e)

        publishing = (ROOT / "PUBLISHING.md").read_text(encoding="utf-8")
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        reporting = (ROOT / "docs" / "PROBLEM_REPORTING.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "MANAGED_SKILL_UPDATE_GUIDE.md").read_text(encoding="utf-8")
        active_release_docs = "\n".join((publishing, security, reporting, guide)).lower()
        self.assertNotIn("new immutable release", active_release_docs)
        self.assertNotIn("publish one immutable release", active_release_docs)
        self.assertIn("gh release verify", publishing)
        self.assertIn("policy-only", publishing.lower())
        self.assertIn("Protect version release tags", publishing)
        self.assertIn("ruleset `20781141`", review)
        self.assertIn("immutable=false", review)


if __name__ == "__main__":
    unittest.main()

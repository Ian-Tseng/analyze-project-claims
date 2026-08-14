from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "analyze-project-claims"
AGENT_SKILLS_FIELDS = {
    "allowed-tools",
    "compatibility",
    "description",
    "license",
    "metadata",
    "name",
}


def frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise AssertionError("SKILL.md frontmatter is missing")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise AssertionError("SKILL.md frontmatter is not closed") from exc

    values: dict[str, str] = {}
    for line in lines[1:end]:
        if line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


class AgentCompatibilityTests(unittest.TestCase):
    def test_skill_frontmatter_is_portable_agent_skills_metadata(self) -> None:
        metadata = frontmatter((SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8"))
        self.assertEqual(set(metadata) - AGENT_SKILLS_FIELDS, set())
        self.assertEqual(metadata["name"], SKILL_ROOT.name)
        self.assertTrue(metadata["description"])
        self.assertEqual(metadata["license"], "MIT")

    def test_claude_layout_preserves_verified_package(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claude-skill-install-") as temporary:
            destination = Path(temporary) / ".claude" / "skills" / SKILL_ROOT.name
            manifest_path = SKILL_ROOT / "references" / "package-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for entry in manifest["files"]:
                source = SKILL_ROOT / entry["path"]
                target = destination / entry["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            copied_manifest = destination / "references" / "package-manifest.json"
            copied_manifest.write_bytes(manifest_path.read_bytes())
            result = subprocess.run(
                [
                    sys.executable,
                    str(destination / "scripts" / "update_policy.py"),
                    "--skill-root",
                    str(destination),
                    "--state-dir",
                    str(Path(temporary) / "state"),
                    "--format",
                    "json",
                    "verify-package",
                ],
                cwd=temporary,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "PACKAGE_VERIFIED")

    def test_docs_bound_managed_claude_evidence(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        publishing = (ROOT / "PUBLISHING.md").read_text(encoding="utf-8")
        guide = (ROOT / "docs" / "MULTI_AGENT_SKILL_COMPATIBILITY_GUIDE.md").read_text(
            encoding="utf-8"
        )
        evidence = (ROOT / "docs" / "CLAUDE_CODE_E2E_LOG.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("## Install", readme)
        self.assertIn("### Codex", readme)
        self.assertIn("### Claude Code", readme)
        self.assertIn("--agent claude-code", readme)
        self.assertIn("/analyze-project-claims", readme)
        self.assertIn("GitHub CLI-tracked standalone", readme)
        self.assertIn("MULTI_AGENT_SKILL_COMPATIBILITY_GUIDE.md", readme)
        self.assertIn("CLAUDE_CODE_E2E_LOG.md", readme)
        self.assertIn("gh skill list --agent claude-code", publishing)
        self.assertIn("neutral consumer directory", publishing)
        self.assertIn("structural Agent Skills compatibility", publishing)
        self.assertIn("Do not claim Claude Code runtime", publishing)
        self.assertIn("Client discovery", guide)
        self.assertIn("Real invocation", guide)
        self.assertIn("Live replacement", guide)
        self.assertIn("RUNTIME NOT OBSERVED", evidence)
        self.assertIn(
            "7ceed9ccd383001ca687f3c2a47f0414244f2b3dcef72e371eccdca7aab63d6f",
            evidence,
        )


if __name__ == "__main__":
    unittest.main()

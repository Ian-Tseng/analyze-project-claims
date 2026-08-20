from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "skills" / "analyze-project-claims" / "scripts" / "managed_fleet.py"
CORE = ROOT / ".github" / "actions" / "managed-skill-core" / "managed_skill_core.py"
WORKFLOW = ROOT / ".github" / "workflows" / "managed-skill-repair.yml"
SHA = "a" * 40


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ManagedFleetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fleet = load_module("test_managed_fleet_cli", FLEET)
        cls.core = load_module("test_managed_fleet_core", CORE)

    def policy(self) -> dict[str, object]:
        return self.fleet.build_policy(
            repository="Ian-Tseng/example-skill",
            repository_id=123456,
            skill="example-skill",
            package_root="skills/example-skill",
            workflow_sha=SHA,
            validation_profile="python-unittest-package-v1",
            repair_enabled=True,
        )

    def event(self, policy: dict[str, object]) -> dict[str, object]:
        return {
            "action": "labeled",
            "label": {"name": policy["triage"]["label"]},
            "sender": {"login": "Ian-Tseng"},
            "repository": {
                "id": policy["repository"]["id"],
                "full_name": policy["repository"]["full_name"],
                "default_branch": "main",
            },
            "issue": {
                "number": 17,
                "node_id": "I_kwDOExample",
                "state": "open",
                "body": "Bounded quality report body.",
                "updated_at": "2026-08-20T12:00:00Z",
                "labels": [{"name": policy["triage"]["label"]}],
            },
        }

    def test_closed_policy_rejects_unknown_keys_and_traversal(self) -> None:
        policy = self.policy()
        self.assertEqual(self.fleet.validate_policy(policy)["protocol"], "ian-tseng-managed-skill-repair/v1")
        with self.assertRaises(self.fleet.FleetError):
            self.fleet.validate_policy({**policy, "command": "curl example.invalid"})
        escaped = json.loads(json.dumps(policy))
        escaped["skill"]["package_roots"] = ["../outside"]
        with self.assertRaises(self.fleet.FleetError):
            self.fleet.validate_policy(escaped)

    def test_init_preview_then_apply_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preview = subprocess.run(
                [
                    sys.executable,
                    str(FLEET),
                    "--format",
                    "json",
                    "init",
                    "--repo-root",
                    str(root),
                    "--repository",
                    "Ian-Tseng/example-skill",
                    "--repository-id",
                    "123456",
                    "--skill",
                    "example-skill",
                    "--package-root",
                    "skills/example-skill",
                    "--workflow-sha",
                    SHA,
                    "--validation-profile",
                    "python-unittest-package-v1",
                    "--enable-repair",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(json.loads(preview.stdout)["status"], "PREVIEW_READY")
            self.assertFalse((root / ".github" / "managed-skill-policy.json").exists())

            applied = subprocess.run(preview.args + ["--apply"], text=True, encoding="utf-8", capture_output=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(json.loads(applied.stdout)["changed"], True)
            again = subprocess.run(preview.args + ["--apply"], text=True, encoding="utf-8", capture_output=True)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(json.loads(again.stdout)["status"], "ALREADY_CONFIGURED")
            self.assertEqual(json.loads(again.stdout)["changed"], False)

    def test_caller_is_sha_pinned_and_contains_no_central_implementation(self) -> None:
        caller = self.fleet.render_caller(SHA)
        self.assertIn(f"Ian-Tseng/analyze-project-claims/.github/workflows/managed-skill-repair.yml@{SHA}", caller)
        self.assertIn(f"workflow-sha: {SHA}", caller)
        self.assertIn("secrets:", caller)
        self.assertIn("OPENAI_API_KEY", caller)
        self.assertNotIn("inherit", caller)
        self.assertNotIn("gh pr create", caller)
        self.assertNotIn("python ", caller)

    def test_intake_binds_all_authorization_inputs_and_is_deterministic(self) -> None:
        policy = self.policy()
        event = self.event(policy)
        first = self.core.build_authorization(
            policy=policy,
            event=event,
            base_sha="b" * 40,
            workflow_sha=SHA,
            nonce="run-12-attempt-1",
            now_utc="2026-08-20T12:01:00Z",
        )
        second = self.core.build_authorization(
            policy=policy,
            event=event,
            base_sha="b" * 40,
            workflow_sha=SHA,
            nonce="run-12-attempt-1",
            now_utc="2026-08-20T12:01:00Z",
        )
        self.assertEqual(first, second)
        self.assertRegex(first["authorization_id"], r"^[0-9a-f]{64}$")
        manifest = first["manifest"]
        for key in (
            "repository_id",
            "repository_full_name",
            "issue_node_id",
            "issue_number",
            "issue_body_sha256",
            "label_state_sha256",
            "issue_updated_at",
            "base_sha",
            "policy_sha256",
            "workflow_sha",
            "nonce",
            "expires_at_utc",
        ):
            self.assertIn(key, manifest)

        edited = self.event(policy)
        edited["issue"]["body"] += " edited"
        self.assertNotEqual(
            first["authorization_id"],
            self.core.build_authorization(
                policy=policy,
                event=edited,
                base_sha="b" * 40,
                workflow_sha=SHA,
                nonce="run-12-attempt-1",
                now_utc="2026-08-20T12:01:00Z",
            )["authorization_id"],
        )

    def test_configuration_dry_run_emits_an_expiring_authorization_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy_path = root / ".github" / "managed-skill-policy.json"
            policy_path.parent.mkdir(parents=True)
            policy_path.write_text(json.dumps(self.policy()), encoding="utf-8")
            event_path = root / "event.json"
            event_path.write_text(json.dumps(self.event(self.policy())), encoding="utf-8")
            runner_temp = root / "runner"
            runner_temp.mkdir()
            summary = root / "summary.md"
            output = root / "output.txt"

            with mock.patch.dict(
                self.core.os.environ,
                {
                    "RUNNER_TEMP": str(runner_temp),
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "GITHUB_OUTPUT": str(output),
                },
                clear=False,
            ):
                self.core._intake(
                    root,
                    Path(".github/managed-skill-policy.json"),
                    event_path,
                    "b" * 40,
                    SHA,
                    "run-12-attempt-1",
                    True,
                )

            result = json.loads(
                (runner_temp / "managed-repair" / "authorization.json").read_text(
                    encoding="utf-8"
                )
            )
            manifest = result["manifest"]
            self.assertEqual(manifest["kind"], "configuration_dry_run")
            self.assertGreater(
                self.core._iso(manifest["expires_at_utc"]),
                self.core._iso(manifest["created_at_utc"]),
            )
            self.assertIn(manifest["expires_at_utc"], summary.read_text(encoding="utf-8"))
            self.assertIn("authorization-path=", output.read_text(encoding="utf-8"))

    def test_reusable_workflow_has_privilege_and_provenance_boundaries(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_call:", workflow)
        self.assertIn("workflow-sha:", workflow)
        self.assertEqual(workflow.count("${{ inputs.workflow-sha }}"), 3)
        self.assertNotIn("github.workflow_sha", workflow)
        operations = (ROOT / "docs" / "MANAGED_FLEET_OPERATIONS.md").read_text(encoding="utf-8")
        self.assertIn("Do not use `github.workflow_sha`", operations)
        self.assertIn("run 32392414122", operations)
        self.assertIn("run 32398400200", operations)
        self.assertIn("same two-hour expiry boundary", operations)
        self.assertIn("permissions: {}", workflow)
        self.assertIn("environment: managed-repair-agent", workflow)
        self.assertIn("environment: managed-repair-publish", workflow)
        self.assertGreaterEqual(workflow.count("uses: $/.github/actions/managed-skill-core"), 3)
        self.assertNotIn("secrets: inherit", workflow)
        self.assertEqual(workflow.count("secrets.OPENAI_API_KEY"), 1)
        uses = re.findall(r"(?m)^\s+-?\s*uses:\s+([^\s#]+)", workflow)
        external = [item for item in uses if not item.startswith("$/")]
        self.assertTrue(external)
        self.assertTrue(all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", item) for item in external))
        candidate = workflow[workflow.index("  candidate:"):workflow.index("  validate:")]
        self.assertNotIn("contents: write", candidate)
        self.assertNotIn("pull-requests: write", candidate)
        publish = workflow[workflow.index("  publish-draft:"):]
        self.assertIn("pull-requests: write", publish)
        self.assertIn("issues: write", publish)

    def test_required_operator_documents_exist(self) -> None:
        for name in (
            "MANAGED_FLEET_QUICKSTART.md",
            "MANAGED_FLEET_OPERATIONS.md",
            "MANAGED_REPAIR_WALKTHROUGH.md",
            "MULTI_AGENT_INSTALL_TOPOLOGY.md",
            "MANAGED_FLEET_SUPPORT_MATRIX.md",
        ):
            self.assertTrue((ROOT / "docs" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()

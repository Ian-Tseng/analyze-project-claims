import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CodexPluginBundleTests(unittest.TestCase):
    def test_repository_root_is_the_single_canonical_plugin_tree(self) -> None:
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "analyze-project-claims")
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["version"], (ROOT / "VERSION").read_text(encoding="utf-8").strip())
        self.assertFalse((ROOT / "plugins").exists(), "Do not commit a duplicate discoverable skill tree.")

    def test_stop_hook_is_bounded_and_uses_plugin_private_state(self) -> None:
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        groups = hooks["hooks"]["Stop"]
        self.assertEqual(len(groups), 1)
        self.assertNotIn("matcher", groups[0], "Codex ignores Stop matchers.")
        handlers = groups[0]["hooks"]
        self.assertEqual(len(handlers), 1)
        handler = handlers[0]
        self.assertEqual(handler["type"], "command")
        self.assertEqual(handler["timeout"], 5)
        self.assertIn("PLUGIN_ROOT", handler["command"])
        self.assertIn("PLUGIN_DATA", handler["command"])
        self.assertIn("PLUGIN_ROOT", handler["commandWindows"])
        self.assertIn("PLUGIN_DATA", handler["commandWindows"])
        serialized = json.dumps(handler).lower()
        self.assertNotIn("transcript", serialized)
        self.assertNotIn("http", serialized)

    @unittest.skipUnless(os.name == "nt", "Windows hook shell regression")
    def test_windows_stop_hook_runs_real_receipt_lifecycle_in_both_shells(self) -> None:
        scripts = ROOT / "skills" / "analyze-project-claims" / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            from _internal.skill_quality import contract
            from _internal.skill_quality.store import QualityStore
        finally:
            sys.path.pop(0)
        handler = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["Stop"][0]["hooks"][0]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        receipt = contract.create_receipt(
            owner="Ian-Tseng", repository="example-producer", skill="example-producer",
            version="1.2.3", package_digest_sha256="a" * 64,
            outcome="completed_with_limitations", quality_signal="claim_evidence_gap",
            requested_action="analyze_quality", created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        event = {
            "hook_event_name": "Stop", "session_id": "shell-regression",
            "turn_id": "turn-1", "stop_hook_active": False,
            "last_assistant_message": "done\n" + contract.format_marker(receipt),
        }
        with tempfile.TemporaryDirectory(prefix="claims-hook-") as temporary:
            # Values must stay data: these characters have meaning to one or both shells.
            special = " space & (group) $literal %literal% !literal! 'quote' `tick"
            plugin_root = Path(temporary) / ("plugin" + special)
            target_scripts = plugin_root / "skills" / "analyze-project-claims" / "scripts"
            shutil.copytree(scripts, target_scripts, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            for shell, prefix in (
                ("cmd", [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c"]),
                ("powershell", ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]),
            ):
                with self.subTest(shell=shell):
                    data = Path(temporary) / (shell + " data" + special)
                    environment = dict(os.environ, PLUGIN_ROOT=str(plugin_root), PLUGIN_DATA=str(data))

                    def invoke(payload: dict) -> dict:
                        result = subprocess.run(
                            (subprocess.list2cmdline(prefix) + " " + handler["commandWindows"])
                            if shell == "cmd" else [*prefix, handler["commandWindows"]],
                            input=json.dumps(payload), text=True, encoding="utf-8",
                            capture_output=True, env=environment, cwd=temporary,
                            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stderr.strip(), "")
                        return json.loads(result.stdout)

                    self.assertEqual(invoke({**event, "last_assistant_message": "no receipt"}), {})
                    first = invoke(event)
                    self.assertEqual(first["decision"], "block")
                    self.assertIn(receipt["receipt_digest_sha256"], first["reason"])
                    self.assertEqual(invoke(event), {}, "A replay must not request a second continuation.")
                    self.assertEqual(invoke({**event, "turn_id": "turn-2", "stop_hook_active": True}), {})
                    status = QualityStore(data / "skill-quality").status()
                    self.assertEqual(status["receipt_count"], 1)
                    self.assertEqual(status["pending_receipts"], 1)
                    self.assertEqual(status["proposal_count"], 0)
                    self.assertEqual(status["outbound_actions"], 0)

    def test_repository_marketplace_points_to_root_plugin(self) -> None:
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        entry = marketplace["plugins"][0]
        self.assertEqual(entry["name"], "analyze-project-claims")
        self.assertEqual(entry["source"], {"source": "local", "path": "./"})
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")
        self.assertEqual(entry["policy"]["authentication"], "ON_INSTALL")


if __name__ == "__main__":
    unittest.main()

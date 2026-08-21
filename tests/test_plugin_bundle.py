import json
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

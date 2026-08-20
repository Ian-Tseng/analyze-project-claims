import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "analyze-project-claims" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _internal.safe_process import ExecutableResolutionError, resolve_executable  # noqa: E402


class SafeProcessTests(unittest.TestCase):
    def test_bare_command_excludes_current_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="safe-process-") as temporary:
            base = Path(temporary)
            current = base / "project"
            trusted = base / "trusted-bin"
            current.mkdir()
            trusted.mkdir()
            name = "gh.exe" if os.name == "nt" else "gh"
            local = current / name
            expected = trusted / name
            local.write_text("local", encoding="utf-8")
            expected.write_text("trusted", encoding="utf-8")
            if os.name != "nt":
                local.chmod(local.stat().st_mode | stat.S_IXUSR)
                expected.chmod(expected.stat().st_mode | stat.S_IXUSR)
            path_value = os.pathsep.join((str(current), str(trusted)))
            prior = Path.cwd()
            try:
                os.chdir(current)
                with mock.patch.dict(os.environ, {"PATH": path_value}, clear=False):
                    resolved = resolve_executable("gh")
            finally:
                os.chdir(prior)
            self.assertEqual(Path(resolved), expected.resolve())

    def test_relative_path_with_directory_is_rejected(self) -> None:
        with self.assertRaises(ExecutableResolutionError):
            resolve_executable("./gh")


if __name__ == "__main__":
    unittest.main()

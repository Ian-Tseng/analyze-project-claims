"""Regressions from independent review of user control and adapter compatibility."""
from unittest.mock import patch
from pathlib import Path
import tempfile
from types import SimpleNamespace
import stat
import os
import subprocess
import unittest
import test_long_running_subagents as fixtures
import subagent_mode
from long_running_controller import ContractError, snapshot


class ReviewedEdgeCases(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SubagentModeTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_projection_failure_cannot_prevent_user_pause_or_stop(self):
        f = self.fixture
        f.start()
        with patch('subagent_mode.materialize', side_effect=OSError('locked report fixture')):
            for value in ('paused', 'stopped'):
                result = f.controller.control(value, 'Explicit fixture user instruction')
                self.assertEqual(result['status'], value)
                self.assertIn('report_error', result)
                with f.controller.locked():
                    state = f.controller._load(sync_reports=False)[0]
                self.assertEqual(state['control'], value)
        self.assertEqual(f.controller.next()['status'], 'STOPPED')

    def test_legacy_no_tool_reviewer_adapter_is_rejected_at_init(self):
        f = self.fixture
        for name in ('codex_reviewer.py', 'CODEX_REVIEWER.PY'):
            f.config['reviewer_command'] = ['python', '/some/path/' + name]
            with self.subTest(name=name), self.assertRaisesRegex(ContractError, 'Legacy'):
                f.controller.init(f.config)

    def reparse_lstat(self, target):
        original = Path.lstat
        target = target.resolve()
        def inspect(path, *args, **kwargs):
            observed = original(path, *args, **kwargs)
            if path.absolute() == target:
                return SimpleNamespace(st_mode=observed.st_mode,
                                       st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
            return observed
        return inspect

    def test_in_root_evidence_reparse_is_rejected_without_is_junction(self):
        f = self.fixture
        linked = f.root / "linked"
        linked.mkdir()
        (linked / "evidence.txt").write_text("in-root reparse fixture", encoding="utf-8")
        f.config["evidence"] = ["linked/evidence.txt"]
        with patch.object(Path, "lstat", self.reparse_lstat(linked)), \
             patch.object(Path, "is_junction", return_value=False, create=True):
            with self.assertRaisesRegex(ContractError, "Evidence may not cross links"):
                snapshot(dict(f.config, project_root=str(f.root.resolve())))

    def test_report_directory_reparse_is_rejected_without_is_junction(self):
        f = self.fixture
        f.start()
        with f.controller.locked():
            state = f.controller._load(sync_reports=False)[0]
        reports = f.controller.root / "reports"
        before = (reports / "current.json").read_bytes()
        with patch.object(Path, "lstat", self.reparse_lstat(reports)), \
             patch.object(Path, "is_junction", return_value=False, create=True):
            with self.assertRaisesRegex(ContractError, "Report directory may not cross links"):
                subagent_mode.materialize(state, f.controller.root)
        self.assertEqual((reports / "current.json").read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "Native Windows junction behavior")
    def test_native_windows_in_root_junction_is_rejected(self):
        f = self.fixture
        target = f.root / "actual"
        target.mkdir()
        (target / "evidence.txt").write_text("native junction fixture", encoding="utf-8")
        junction = f.root / "junction"
        process = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        f.config["evidence"] = ["junction/evidence.txt"]
        with patch.object(Path, "is_junction", return_value=False, create=True):
            with self.assertRaisesRegex(ContractError, "Evidence may not cross links"):
                snapshot(dict(f.config, project_root=str(f.root.resolve())))
        self.assertEqual((target / "evidence.txt").read_text(encoding="utf-8"), "native junction fixture")

    def test_unreadable_link_metadata_fails_closed(self):
        f = self.fixture
        f.start()
        with f.controller.locked():
            state = f.controller._load(sync_reports=False)[0]
        original = Path.lstat
        for target, action in ((f.root / "evidence.txt", lambda: snapshot(dict(f.config, project_root=str(f.root.resolve())))),
                               (f.controller.root / "reports", lambda: subagent_mode.materialize(state, f.controller.root))):
            resolved_target = target.resolve()
            def inspect(path, *args, **kwargs):
                if path.absolute() == resolved_target:
                    raise PermissionError("fixture link metadata unavailable")
                return original(path, *args, **kwargs)
            with self.subTest(path=str(target)), patch.object(Path, "lstat", inspect), \
                 patch.object(Path, "is_junction", return_value=False, create=True):
                with self.assertRaises(PermissionError):
                    action()

    def test_reserved_windows_report_name_is_rejected(self):
        f = self.fixture
        f.config['subagent_mode']['reports'][0]['id'] = 'con'
        with self.assertRaisesRegex(ContractError, 'Reserved'):
            f.controller.init(f.config)


if __name__ == '__main__':
    unittest.main()

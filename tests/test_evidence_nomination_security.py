from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import concurrent.futures
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "skills/analyze-project-claims/scripts"))
from _nomination import filesystem as fs
from _nomination.common import Failure, Deadline, parse_json, relative_path
from _internal.component_evidence import map_guard, local_io
from _nomination.engine import Context
from _nomination.common import canonical

from nomination_runtime_fixtures import refresh_component_map

GOLDEN = ROOT / "contracts/evidence-nomination/v1/golden"


class NominationSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nomination-security-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_temporary_substitution_cannot_report_success_with_wrong_bytes(self):
        destination = self.root / "candidate.json"
        original_link = os.link
        attempted = []
        def substitute(source, target, **kwargs):
            attempted.append(True)
            # Same-user interference at the publication boundary. Windows may
            # prevent deletion while the publisher retains its file handle.
            replacement = self.root / "replacement"
            replacement.write_bytes(b"tampered")
            try:
                os.replace(replacement, self.root / source)
            except OSError:
                pass
            return original_link(source, target, **kwargs)
        try:
            with patch.object(fs.os, "link", side_effect=substitute):
                fs.atomic_create(destination, b"reviewed")
        except Failure as exc:
            self.assertEqual(exc.exit_code, 5)
            self.assertTrue(exc.changed)
            self.assertIn(str(destination), exc.artifacts)
        else:
            self.assertEqual(destination.read_bytes(), b"reviewed")
        self.assertTrue(attempted)

    def test_native_snapshot_does_not_read_through_replaced_parent(self):
        parent = self.root / "local"; parent.mkdir()
        outside = self.root / "outside"; outside.mkdir()
        source = parent / "input.json"
        source.write_bytes(b'{"origin":"local"}')
        (outside / "input.json").write_bytes(b'{"origin":"outside"}')
        probe = self.root / "probe"
        try:
            probe.symlink_to(outside, target_is_directory=True); probe.unlink()
        except OSError:
            self.skipTest("Directory symlinks unavailable for this account")
        original_open = os.open
        def swap(path, flags, *args, **kwargs):
            if Path(path) == source:
                parent.rename(self.root / "displaced")
                parent.symlink_to(outside, target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)
        try:
            with patch.object(map_guard.os, "open", side_effect=swap):
                value, _ = map_guard.snapshot(source)
        except map_guard.MapGuardError:
            pass
        else:
            self.assertEqual(value, {"origin":"local"})

    def test_dotdot_absolute_arguments_are_rejected_before_normalizing(self):
        for path in (str(self.root / "evidence" / ".." / "map.json"),):
            with self.assertRaises(Failure):
                fs.absolute(path)

    def test_invisible_identifier_and_windows_ambiguous_paths_are_rejected(self):
        for path in ("a?b.txt", "a*b.txt", "a|b.txt", "a<z.txt", 'a"b.txt', "a/COM1.txt", "NUL", "a:stream", "a/../b", "a/\u202eb"):
            with self.subTest(path=path), self.assertRaises(Failure):
                relative_path(path)

    def project(self):
        project = self.root / "project"
        shutil.copytree(GOLDEN / "project", project)
        request = refresh_component_map(project, json.loads((GOLDEN / "gap-request.json").read_bytes()))
        return project, request

    def test_shared_read_pins_or_detects_parent_rename(self):
        parent = self.root / "parent"; parent.mkdir()
        path = parent / "source.txt"; path.write_bytes(b"source")
        moved = self.root / "moved"
        attempted = []
        if os.name == "nt":
            original = local_io.win_open
            def opening(target, directory=False):
                handle = original(target, directory=directory)
                if Path(target) == parent and directory and not attempted:
                    attempted.append(True)
                    try:
                        parent.rename(moved)
                        parent.mkdir()
                        (parent / path.name).write_bytes(b"replacement")
                    except OSError:
                        pass
                return handle
            with patch.object(local_io, "win_open", side_effect=opening):
                try:
                    value = fs.safe_read(path, 100)
                except Failure:
                    pass
                else:
                    self.assertEqual(value, b"source")
        else:
            original = os.read
            def reading(fd, size):
                if not attempted:
                    attempted.append(True); parent.rename(moved); parent.mkdir()
                    (parent / path.name).write_bytes(b"replacement")
                return original(fd, size)
            with patch.object(local_io.os, "read", side_effect=reading), self.assertRaises(Failure):
                fs.safe_read(path, 100)
        self.assertTrue(attempted)

    def test_shared_read_blocks_or_detects_in_place_mutation(self):
        path = self.root / "source.txt"; path.write_bytes(b"initial")
        initial = path.stat()
        original = os.read
        attempted = []
        def changing(fd, size):
            if not attempted:
                attempted.append(True)
                try:
                    path.write_bytes(b"changed")
                    os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns))
                except OSError:
                    self.assertEqual(os.name, "nt")
            return original(fd, size)
        with patch.object(local_io.os, "read", side_effect=changing):
            if os.name == "nt":
                self.assertEqual(fs.safe_read(path, 100), b"initial")
            else:
                with self.assertRaises(Failure): fs.safe_read(path, 100)
        self.assertTrue(attempted)

    def test_hard_linked_corpus_alias_is_excluded(self):
        project, request = self.project()
        outside = self.root / "outside.txt"; outside.write_bytes(b"Metric accuracy is 0.91.\n")
        os.link(outside, project / "evidence/alias.txt")
        bundle = Context(request, project, project / "map", output=project / ".analyze-project-claims/nominations").build()
        self.assertNotIn("evidence/alias.txt", [item["path"] for item in bundle["corpus"]])
        self.assertIn({"reason":"link_or_reparse", "count":1}, bundle["exclusions"])

    def test_concurrent_publishers_never_overwrite_each_other(self):
        path = self.root / "candidate.json"
        def create(data):
            try: fs.atomic_create(path, data); return data
            except (OSError, Failure): return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, (b"first", b"second")))
        winners = [value for value in results if value is not None]
        self.assertEqual(winners, [path.read_bytes()])
        self.assertFalse(list(self.root.glob(".nomination-*")))

    def test_cleanup_failure_reports_surviving_artifacts(self):
        path = self.root / "candidate.json"
        original = os.unlink
        def refuse_temporary(name, **kwargs):
            if Path(name).name.startswith(".nomination-"):
                raise PermissionError("synthetic cleanup failure")
            return original(name, **kwargs)
        with patch.object(fs.os, "unlink", side_effect=refuse_temporary), self.assertRaises(Failure) as caught:
            fs.atomic_create(path, b"complete")
        self.assertEqual(caught.exception.exit_code, 5)
        self.assertTrue(caught.exception.changed)
        self.assertEqual(path.read_bytes(), b"complete")
        self.assertEqual({str(p) for p in self.root.iterdir()}, set(caught.exception.artifacts))

    def test_duplicate_nonfinite_float_surrogate_and_deep_json_refused(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1.1}',
                    b'{"x":"\\ud800"}', b'['*70+b'0'+b']'*70, b'\xef\xbb\xbf{}'):
            with self.subTest(raw=raw[:30]), self.assertRaises(Failure): parse_json(raw)

    def test_secret_unicode_binary_lfs_and_archive_matrix_is_content_free(self):
        project, request = self.project()
        samples = {
            "private.txt": b"-----BEGIN OPENSSH PRIVATE KEY-----\n",
            "token.txt": b"github_pat_abcdefghijklmnopqrstuvwxyz1234567890",
            "quoted.txt": b'{"password":"privatevalue12345"}',
            "bidi.txt": "Metric accuracy \u202e0.91".encode(),
            "zero-width.txt": "Metric accuracy \u200b0.91".encode(),
            "bom.txt": b"\xef\xbb\xbfMetric accuracy 0.91",
            "utf16.txt": "Metric accuracy 0.91".encode("utf-16"),
            "lfs.txt": b"version https://git-lfs.github.com/spec/v1\noid sha256:1111\n",
            "archive.txt": b"PK\x03\x04Metric accuracy 0.91",
        }
        for name, raw in samples.items(): (project / "evidence" / name).write_bytes(raw)
        bundle = Context(request, project, project / "map", output=project / ".analyze-project-claims/nominations").build()
        self.assertEqual(len(bundle["nominations"]), 3)
        self.assertEqual({x["reason"]:x["count"] for x in bundle["exclusions"]},
                         {"secret":3, "unsafe_unicode":2, "binary_or_encoding":2, "lfs_pointer":1, "archive":1})
        raw = canonical(bundle)
        for text in (b"privatevalue", b"abcdefghijklmnopqrstuvwxyz", b"private.txt", b"bidi.txt"):
            self.assertNotIn(text, raw)

    def test_literal_queries_do_not_execute_regex_or_shell_text(self):
        project, request = self.project()
        text = "$(touch marker) [a-z]+ .*"
        (project / "evidence/literal.txt").write_text(text+"\n", encoding="utf-8")
        request["requirements"] = [dict(request["requirements"][0], all_terms=[text], any_terms=[], exclude_terms=[])]
        bundle = Context(request, project, project / "map", output=project / ".analyze-project-claims/nominations").build()
        self.assertEqual([x["path"] for x in bundle["nominations"]], ["evidence/literal.txt"])
        self.assertFalse((project / "marker").exists())

    def test_unicode_spellings_remain_distinct(self):
        project, request = self.project()
        (project / "evidence/unicode.txt").write_bytes("caf\u00e9\ncafe\u0301\n".encode("utf-8"))
        request["requirements"] = [dict(request["requirements"][0], all_terms=["caf\u00e9"], any_terms=[], exclude_terms=[])]
        bundle = Context(request, project, project / "map", output=project / ".analyze-project-claims/nominations").build()
        hits = [x for x in bundle["nominations"] if x["path"] == "evidence/unicode.txt"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["line_start"], 1)
        self.assertEqual(hits[0]["range_sha256"], hashlib.sha256("caf\u00e9\n".encode()).hexdigest())

    def test_case_colliding_names_abort(self):
        project, request = self.project()
        upper = project / "evidence/Same.txt"
        lower = project / "evidence/same.txt"
        upper.write_bytes(b"Metric accuracy 0.91")
        if lower.exists():
            self.skipTest("This filesystem cannot hold case-distinct names")
        lower.write_bytes(b"Metric accuracy 0.91")
        with self.assertRaisesRegex(Failure, "safety_refusal"):
            Context(request, project, project / "map", output=project / ".analyze-project-claims/nominations").build()

    @unittest.skipIf(os.name == "nt", "POSIX FIFO test")
    def test_fifo_is_excluded_without_blocking(self):
        project, request = self.project()
        os.mkfifo(project / "evidence/pipe")
        bundle = Context(request, project, project / "map", output=project / ".analyze-project-claims/nominations").build()
        self.assertIn({"reason":"path_policy", "count":1}, bundle["exclusions"])

    def test_range_and_total_byte_caps_are_deterministic_partial(self):
        project, request = self.project()
        request["resource_policy"]["max_range_bytes"] = 10
        request["resource_policy"]["max_excerpt_bytes"] = 10
        bundle = Context(request, project, project / "map", output=project / ".analyze-project-claims/nominations").build()
        self.assertEqual(bundle["completeness"], "partial")
        self.assertEqual(bundle["nominations"], [])
        self.assertEqual(bundle["truncations"][0]["budget"], "max_range_bytes")
        request = refresh_component_map(project, json.loads((GOLDEN / "gap-request.json").read_bytes()))
        request["resource_policy"]["max_total_bytes"] = 50
        request["resource_policy"]["max_file_bytes"] = 50
        bundle = Context(request, project, project / "map", output=project / ".analyze-project-claims/nominations").build()
        self.assertEqual(bundle["completeness"], "partial")
        self.assertTrue(any(t["budget"] == "max_total_bytes" for t in bundle["truncations"]))

    def test_timeout_after_open_returns_no_bytes_or_artifact(self):
        path = self.root / "source.txt"; path.write_bytes(b"text")
        deadline = Deadline(1); deadline.until = -1
        with self.assertRaises(Failure) as caught: fs.safe_read(path, 100, deadline)
        self.assertEqual(caught.exception.code, "timeout")
        self.assertEqual(list(self.root.iterdir()), [path])


if __name__ == "__main__":
    unittest.main()

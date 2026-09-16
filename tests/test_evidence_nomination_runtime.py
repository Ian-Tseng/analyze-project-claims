from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from nomination_contract_support import canonical, check_schema, digest, load
from nomination_runtime_fixtures import refresh_claim_record, refresh_component_map

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts/evidence-nomination/v1"
GOLDEN = CONTRACT / "golden"
CLI = ROOT / "scripts/evidence_nomination.py"


class NominationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nomination-runtime-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve() / "project"
        shutil.copytree(GOLDEN / "project", self.project)
        self.request = self.project / "request.json"
        self.output = self.project / ".analyze-project-claims/nominations"
        self.value = refresh_component_map(self.project, load(GOLDEN / "gap-request.json"))
        self.save()
        self.before = (self.project / "map/accepted-map.json").read_bytes()

    def save(self):
        self.request.write_bytes(canonical(self.value) + b"\n")

    def cli(self, command="nominate", *extra, expected=0):
        args = [sys.executable, str(CLI), command]
        if command in ("preflight", "nominate"):
            args += ["--request", str(self.request), "--project-root", str(self.project), "--map-root", str(self.project / "map")]
        if command == "nominate":
            args += ["--out-dir", str(self.output)]
        result = subprocess.run(args + ["--format", "json", *extra], cwd=self.project, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt["network"])
        self.assertFalse(receipt["accepted_state_changed"])
        self.assertEqual((self.project / "map/accepted-map.json").read_bytes(), self.before)
        return receipt

    def bundle(self):
        receipt = self.cli()
        return Path(receipt["artifact_path"]), load(receipt["artifact_path"]), receipt

    def test_preflight_does_not_write(self):
        receipt = self.cli("preflight")
        self.assertFalse(receipt["changed"])
        self.assertFalse(self.output.exists())

    def test_golden_semantics_and_identical_reuse(self):
        path, bundle, receipt = self.bundle()
        self.assertEqual(receipt["code"], "complete")
        check_schema(bundle, CONTRACT / "bundle.schema.json")
        expected = load(GOLDEN / "bundle.json")
        expected["request"]["map"] = self.value["map"]
        for key in ("request", "corpus", "queries", "nominations", "exclusions", "truncations", "completeness"):
            self.assertEqual(bundle[key], expected[key], key)
        self.assertEqual(bundle["finder"]["implementation_kind"], "runtime")
        data = path.read_bytes()
        reused = self.cli()
        self.assertEqual(reused["code"], "reused_identical")
        self.assertFalse(reused["changed"])
        self.assertEqual(data, path.read_bytes())
        selection = load(path.with_name(bundle["bundle_id"] + ".selection.json"))
        self.assertEqual(selection["selections"], [])
        self.assertIsNone(selection["reviewer_input"])
        check_schema(selection, CONTRACT / "selection.schema.json")

    def test_show_and_verify(self):
        path, bundle, _ = self.bundle()
        shown = self.cli("show", "--bundle", str(path))
        self.assertEqual(shown["nomination_count"], 3)
        verified = self.cli("verify", "--bundle", str(path), "--project-root", str(self.project), "--map-root", str(self.project / "map"))
        self.assertEqual(verified["code"], "verified")
        self.assertFalse(verified["changed"])

    def test_source_and_corpus_drift(self):
        path, _, _ = self.bundle()
        (self.project / "evidence/new.txt").write_text("Metric accuracy is 0.91.\n", encoding="utf-8")
        result = self.cli("verify", "--bundle", str(path), "--project-root", str(self.project), "--map-root", str(self.project / "map"), expected=4)
        self.assertEqual(result["code"], "stale_identity")

    def test_tampered_bundle_and_no_clobber(self):
        path, bundle, _ = self.bundle()
        bundle["nominations"][0]["score"] += 1
        path.write_bytes(canonical(bundle) + b"\n")
        self.cli("show", "--bundle", str(path), expected=4)
        refusal = self.cli(expected=5)
        self.assertEqual(refusal["code"], "recovery_required")
        self.assertEqual(load(path), bundle)

    def test_modified_selection_is_preserved(self):
        path, bundle, _ = self.bundle()
        selection = path.with_name(bundle["bundle_id"] + ".selection.json")
        data = load(selection); data["reviewer_label"] = "human-edited"
        selection.write_bytes(canonical(data) + b"\n")
        before = selection.read_bytes()
        self.cli(expected=5)
        self.assertEqual(selection.read_bytes(), before)

    def test_claim_target_requires_bound_record(self):
        self.value = refresh_claim_record(self.project, load(GOLDEN / "claim-gap-request.json")); self.save()
        self.cli(expected=2)
        receipt = self.cli("nominate", "--record", str(self.project / "record.json"))
        self.assertEqual(load(receipt["artifact_path"])["request"]["target"], self.value["target"])
        self.value["target"]["claim_digest"] = "0" * 64; self.save()
        self.cli("preflight", "--record", str(self.project / "record.json"), expected=4)

    def test_request_normalization(self):
        self.value["requirements"].reverse()
        self.value["requirements"][0]["all_terms"] = ["accuracy", "Metric", "Metric"]
        self.save()
        _, bundle, _ = self.bundle()
        self.assertEqual(bundle["request"], refresh_component_map(self.project, load(GOLDEN / "gap-request.json")))

    def test_invalid_roots_queries_and_json_are_refused(self):
        original = copy.deepcopy(self.value)
        for roots in (["../outside"], ["." , "evidence"], ["evidence", "evidence"], ["NUL"], ["evidence:stream"]):
            self.value = copy.deepcopy(original); self.value["allowed_roots"] = roots; self.save()
            self.cli(expected=2)
        self.value = copy.deepcopy(original)
        self.value["requirements"][0]["all_terms"] = []
        self.value["requirements"][0]["any_terms"] = []; self.save()
        self.cli(expected=2)
        self.request.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
        self.cli(expected=2)
        self.assertFalse(self.output.exists())

    def test_map_raw_byte_drift(self):
        self.value["map"]["file_sha256"] = "0" * 64; self.save()
        self.cli("preflight", expected=4)
        self.assertFalse(self.output.exists())

    def test_zero_and_deterministic_partial_results(self):
        for r in self.value["requirements"]: r["any_terms"] = ["no-such-phrase"]
        self.save(); _, bundle, receipt = self.bundle()
        self.assertEqual(receipt["code"], "zero_nominations")
        self.assertEqual(bundle["nominations"], [])
        self.value = refresh_component_map(self.project, load(GOLDEN / "gap-request.json"))
        self.value["resource_policy"]["max_nominations"] = 1
        self.value["resource_policy"]["max_per_requirement"] = 1
        self.save(); _, bundle, receipt = self.bundle()
        self.assertEqual(receipt["code"], "partial")
        expected = load(GOLDEN / "partial-bundle.json")
        self.assertEqual(bundle["truncations"], expected["truncations"])
        self.assertEqual(bundle["nominations"], expected["nominations"])

    def test_binary_secret_archive_and_control_content_excluded(self):
        sources = {"secret.txt": b"api_key=abcdefgh12345678901234567890\n", "binary.txt": b"\xff\x00", "archive.zip": b"PK\x03\x04", "control.txt": b"Metric\x1b[31m accuracy", "lfs.txt": b"version https://git-lfs.github.com/spec/v1\noid sha256:0000\n"}
        for name, data in sources.items(): (self.project / "evidence" / name).write_bytes(data)
        path, bundle, _ = self.bundle()
        self.assertEqual({x["reason"] for x in bundle["exclusions"]}, {"secret", "binary_or_encoding", "archive", "unsafe_unicode", "lfs_pointer"})
        self.assertNotIn(b"abcdefgh", path.read_bytes())
        self.assertEqual(len(bundle["nominations"]), 3)

    def test_project_modules_never_imported(self):
        sentinel = self.project / "imported.txt"
        (self.project / "json.py").write_text("raise RuntimeError('project module executed')", encoding="utf-8")
        (self.project / "sitecustomize.py").write_text("raise RuntimeError('project startup executed')", encoding="utf-8")
        self.bundle()
        self.assertFalse(sentinel.exists())

    def test_nested_directory_order_is_lexical(self):
        evidence = self.project / "evidence"
        (evidence / "a").mkdir()
        (evidence / "a/first.txt").write_text("Metric accuracy 0.91\n", encoding="utf-8")
        (evidence / "a.txt").write_text("Metric accuracy 0.91\n", encoding="utf-8")
        _, bundle, _ = self.bundle()
        paths = [c["path"] for c in bundle["corpus"]]
        self.assertEqual(paths, sorted(paths))

    def test_project_root_request_replays_without_nominating_its_own_input(self):
        self.value["allowed_roots"] = ["."]; self.save()
        path, bundle, _ = self.bundle()
        self.assertNotIn("request.json", [x["path"] for x in bundle["corpus"]])
        self.cli("verify", "--bundle", str(path), "--project-root", str(self.project), "--map-root", str(self.project / "map"))

    def test_duplicate_query_hits_merge_and_utf8_excerpt_is_whole(self):
        extra = copy.deepcopy(self.value["requirements"][-1]); extra["requirement_id"] = "support-second"
        self.value["requirements"].append(extra)
        self.value["resource_policy"]["max_excerpt_bytes"] = len("Metric accuracy is descriptive; caf".encode("utf-8")) + 1
        self.save()
        _, bundle, _ = self.bundle()
        support = next(n for n in bundle["nominations"] if n["path"].endswith("support.txt"))
        self.assertEqual(len(support["matches"]), 2)
        context = next(n for n in bundle["nominations"] if n["path"].endswith("context.txt"))
        self.assertTrue(context["excerpt_truncated"])
        self.assertTrue(context["excerpt"].endswith("caf"))

    def test_show_never_echoes_rehashed_secret(self):
        path, bundle, _ = self.bundle()
        bundle["nominations"][0]["excerpt"] = "api_key=abcdefgh12345678901234567890"
        payload = {k:v for k,v in bundle.items() if k not in ("bundle_id", "canonical_payload_sha256")}
        bundle["bundle_id"] = "nomination-" + digest(payload)
        bundle["canonical_payload_sha256"] = digest(payload)
        path.write_bytes(canonical(bundle) + b"\n")
        result = self.cli("show", "--bundle", str(path), expected=2)
        self.assertNotIn("abcdefgh", json.dumps(result))

    def test_scanner_opens_no_network_or_process_and_timeout_writes_nothing(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts")))
        from _nomination.engine import Context
        from _nomination.common import Failure
        ctx = Context(self.value, self.project, self.project / "map", request_path=self.request, output=self.output)
        with patch("socket.socket", side_effect=AssertionError("network")), patch("subprocess.Popen", side_effect=AssertionError("process")), patch("os.system", side_effect=AssertionError("shell")):
            self.assertEqual(len(ctx.build()["nominations"]), 3)
        ctx.deadline.until = -1
        with self.assertRaises(Failure) as failure:
            ctx.build()
        self.assertEqual(failure.exception.exit_code, 3)
        self.assertEqual(failure.exception.code, "timeout")
        self.assertFalse(self.output.exists())

    def test_atomic_failure_reports_existing_bundle_and_no_selection(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts")))
        from _nomination.engine import Context
        from _nomination.cli import publish
        from _nomination.common import Failure
        from _nomination.filesystem import atomic_create
        ctx = Context(self.value, self.project, self.project / "map", request_path=self.request, output=self.output)
        bundle = ctx.build()
        def failing_second(path, data):
            if str(path).endswith(".selection.json"):
                raise OSError("synthetic disk failure")
            return atomic_create(path, data)
        with patch("_nomination.cli.atomic_create", side_effect=failing_second), self.assertRaises(Failure) as failure:
            publish(ctx, bundle)
        self.assertEqual(failure.exception.exit_code, 5)
        self.assertTrue(failure.exception.changed)
        self.assertEqual(len(list(self.output.glob("*.bundle.json"))), 1)
        self.assertFalse(list(self.output.glob("*.selection.json")))
        self.assertFalse(list(self.output.glob("*.tmp")))

    def test_output_cannot_cover_a_search_root(self):
        self.output = self.project / "evidence"
        self.cli(expected=2)
        self.assertFalse(list(self.output.glob("*.bundle.json")))

    def test_network_paths_are_refused_before_filesystem_access(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts")))
        from _nomination.filesystem import absolute
        from _nomination.common import Failure
        with self.assertRaises(Failure) as failure:
            absolute("//untrusted-host/share/file.json")
        self.assertEqual(failure.exception.exit_code, 2)

    def test_links_excluded_without_reading_target(self):
        external = Path(self.temp.name) / "outside.txt"
        external.write_text("api_key=abcdefgh12345678901234567890\n", encoding="utf-8")
        link = self.project / "evidence/link.txt"
        try:
            link.symlink_to(external)
        except OSError:
            self.skipTest("This Windows account cannot create symlinks")
        path, bundle, _ = self.bundle()
        self.assertIn({"reason": "link_or_reparse", "count": 1}, bundle["exclusions"])
        self.assertNotIn(b"abcdefgh", path.read_bytes())

    def test_file_and_match_caps_are_partial(self):
        self.value["resource_policy"]["max_files"] = 1; self.save()
        _, bundle, _ = self.bundle()
        self.assertEqual(len(bundle["corpus"]), 1)
        self.assertEqual(bundle["truncations"][0]["budget"], "max_files")
        self.value = refresh_component_map(self.project, load(GOLDEN / "gap-request.json"))
        self.value["resource_policy"]["max_raw_matches"] = 1; self.save()
        _, bundle, _ = self.bundle()
        self.assertEqual(bundle["completeness"], "partial")
        self.assertTrue(any(t["budget"] == "max_raw_matches" for t in bundle["truncations"]))


if __name__ == "__main__":
    unittest.main()

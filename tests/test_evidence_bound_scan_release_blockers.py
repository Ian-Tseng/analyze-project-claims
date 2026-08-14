from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evidence_bound_fixtures import canonical_sha256
import test_evidence_bound_scan_operational as operational


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "analyze-project-claims"


def rewrite_integrity(path: Path, record: dict[str, object]) -> None:
    integrity = record["integrity"]
    assert isinstance(integrity, dict)
    integrity.pop("canonical_payload_sha256", None)
    integrity["canonical_payload_sha256"] = canonical_sha256(record)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


class EvidenceBoundReleaseBlockerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = operational.EvidenceBoundScanOperationalTests(
            methodName="test_help_leads_with_v2_subcommands"
        )

    def append(self, root: Path, map_root: Path, record: Path, **extra: Path):
        args = [
            "append",
            "--record",
            str(record),
            "--map-root",
            str(map_root),
            "--project-root",
            str(root),
            "--log-dir",
            str(extra.get("history", root / "history")),
        ]
        if "reports" in extra:
            args.extend(["--report-dir", str(extra["reports"])])
        return self.helper.run_cli(root, *args)

    def persisted_record(self, root: Path) -> tuple[Path, Path, Path]:
        map_root, record = self.helper.prepare(root)
        history = root / "history"
        result = self.append(root, map_root, record, history=history)
        self.assertEqual(result.returncode, 0, result.stderr)
        return map_root, record, Path(json.loads(result.stdout)["log"])

    def verify(self, root: Path, map_root: Path, record: Path):
        return self.helper.run_cli(
            root,
            "verify",
            "--record",
            str(record),
            "--map-root",
            str(map_root),
            "--project-root",
            str(root),
            "--format",
            "json",
        )

    def test_mutable_external_revision_is_unverifiable_but_full_object_id_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            value = json.loads(record.read_text(encoding="utf-8"))
            value["evidence_items"][0]["source"] = {
                "kind": "https",
                "url": "https://example.com/results",
                "revision": "main",
            }
            value["evidence_items"][0]["method"] = "inspected"
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            rejected = self.append(root, map_root, record)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("EXTERNAL_EVIDENCE_UNVERIFIABLE", rejected.stderr)
            self.assertFalse((root / "history").exists())

            value["evidence_items"][0]["source"]["revision"] = "a" * 40
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            accepted = self.append(root, map_root, record, reports=root / "reports")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            accepted_receipt = json.loads(accepted.stdout)
            persisted = json.loads(Path(accepted_receipt["log"]).read_text(encoding="utf-8"))
            self.assertEqual(persisted["evidence_items"][0]["freshness"], "declared_immutable")
            self.assertIsNone(persisted["evidence_items"][0]["selection_sha256"])
            report = Path(accepted_receipt["report"]).read_text(encoding="utf-8")
            self.assertIn("revision `" + "a" * 40 + "`", report)

    def test_semantic_map_mutation_with_recomputed_integrity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            map_path = map_root / "accepted-map.json"
            value = json.loads(map_path.read_text(encoding="utf-8"))
            value["components"][0]["elements"][0]["target"] = "mutated target"
            integrity = value.pop("integrity")
            integrity["canonical_payload_sha256"] = canonical_sha256(value)
            value["integrity"] = integrity
            map_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            result = self.helper.run_cli(
                root,
                "validate",
                "--record",
                str(record),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("MAP_IDENTITY_MISMATCH", result.stderr)

    def test_recomputed_record_digest_cannot_hide_malformed_or_derived_state(self) -> None:
        mutations = {
            "unknown field": lambda value: value["claims"][0].__setitem__("unknown", True),
            "dangling binding": lambda value: value["bindings"][0].__setitem__("evidence_id", "missing-evidence"),
            "claim digest": lambda value: value["claims"][0].__setitem__("claim_digest", "0" * 64),
            "summary count": lambda value: value["summary"].__setitem__("claim_count", 99),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
                root = Path(temp)
                map_root, _, persisted_path = self.persisted_record(root)
                value = json.loads(persisted_path.read_text(encoding="utf-8"))
                mutate(value)
                rewrite_integrity(persisted_path, value)
                result = self.verify(root, map_root, persisted_path)
                self.assertEqual(result.returncode, 2)
                self.assertRegex(result.stderr, r"RECORD_(?:SCHEMA_UNSUPPORTED|REFERENCE_INVALID|DERIVATION_MISMATCH)")
                self.assertNotIn("Traceback", result.stderr)

    def test_recomputed_digest_cannot_forge_derived_runtime_identities(self) -> None:
        mutations = {
            "engine": (
                lambda value: value["scan"]["engine_identity"].__setitem__("engine_name", "forged-engine"),
                "ENGINE_IDENTITY_MISMATCH",
            ),
            "recorder version": (
                lambda value: value["scan"].__setitem__("recorder_version", "9.9.9"),
                "RECORDER_IDENTITY_MISMATCH",
            ),
            "map path": (
                lambda value: value["scan"]["accepted_map"].__setitem__("path", "forged/accepted-map.json"),
                "MAP_IDENTITY_MISMATCH",
            ),
        }
        for label, (mutate, expected_code) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
                root = Path(temp)
                map_root, _, persisted_path = self.persisted_record(root)
                value = json.loads(persisted_path.read_text(encoding="utf-8"))
                mutate(value)
                rewrite_integrity(persisted_path, value)
                result = self.verify(root, map_root, persisted_path)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertIn(expected_code, json.loads(result.stdout)["codes"])

        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            map_root, _, persisted_path = self.persisted_record(root)
            value = json.loads(persisted_path.read_text(encoding="utf-8"))
            evidence = value["evidence_items"][0]
            evidence["source"]["byte_size"] = 0
            evidence["source"]["media_type"] = "forged/type"
            identity = {
                "source": evidence["source"],
                "locator": evidence["locator"],
                "method": evidence["method"],
                "selection_sha256": evidence["selection_sha256"],
            }
            evidence["identity_sha256"] = canonical_sha256(identity)
            rewrite_integrity(persisted_path, value)
            result = self.verify(root, map_root, persisted_path)
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn("EVIDENCE_DIGEST_MISMATCH", json.loads(result.stdout)["codes"])

    def test_json_and_text_collection_limits_fail_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            record.write_bytes(b"{" + b" " * (5 * 1024 * 1024) + b"}")
            oversized = self.append(root, map_root, record)
            self.assertEqual(oversized.returncode, 2)
            self.assertIn("RECORD_JSON_INVALID", oversized.stderr)
            self.assertFalse((root / "history").exists())

        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            value = json.loads(record.read_text(encoding="utf-8"))
            value["scope"] = [f"item-{index}" for index in range(501)]
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            bounded = self.append(root, map_root, record)
            self.assertEqual(bounded.returncode, 2)
            self.assertIn("RECORD_SCHEMA_UNSUPPORTED", bounded.stderr)
            self.assertFalse((root / "history").exists())
    def test_not_tested_evidence_is_context_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            value = json.loads(record.read_text(encoding="utf-8"))
            value["evidence_items"][0]["method"] = "not_tested"
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            result = self.helper.run_cli(
                root,
                "validate",
                "--record",
                str(record),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("EVIDENCE_METHOD_ROLE_CONFLICT", result.stderr)

    def test_recorder_code_change_invalidates_prior_record(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            copied_skill = root / "copied-skill"
            shutil.copytree(SKILL_ROOT, copied_skill)
            recorder = copied_skill / "scripts" / "record_scan.py"
            map_root, record = self.helper.prepare(root)

            def run(*args: str):
                return subprocess.run(
                    [sys.executable, str(recorder), *args],
                    cwd=root,
                    text=True,
                    capture_output=True,
                    check=False,
                )

            appended = run(
                "append",
                "--record",
                str(record),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--log-dir",
                str(root / "history"),
            )
            self.assertEqual(appended.returncode, 0, appended.stderr)
            persisted = Path(json.loads(appended.stdout)["log"])
            implementation = copied_skill / "scripts" / "_internal" / "evidence_bound_scan.py"
            implementation.write_text(
                implementation.read_text(encoding="utf-8") + "\n# code identity probe\n",
                encoding="utf-8",
            )
            result = run(
                "verify",
                "--record",
                str(persisted),
                "--map-root",
                str(map_root),
                "--project-root",
                str(root),
                "--format",
                "json",
            )
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertIn("RECORDER_IDENTITY_MISMATCH", json.loads(result.stdout)["codes"])
            rendered = run("render", "--record", str(persisted))
            self.assertEqual(rendered.returncode, 2)
            self.assertRegex(rendered.stderr, r"(?:RENDERER|RECORDER)_IDENTITY_MISMATCH")
            self.assertNotIn("# code identity probe", rendered.stdout)

    def test_file_and_parent_symlinks_are_rejected_without_persistence(self) -> None:
        for parent_link in (False, True):
            with self.subTest(parent_link=parent_link), tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
                root = Path(temp)
                map_root, record = self.helper.prepare(root)
                original = root / "receipt.json"
                target_dir = root / "ordinary"
                target_dir.mkdir()
                target = target_dir / "receipt.json"
                original.replace(target)
                try:
                    if parent_link:
                        os.symlink(target_dir, root / "linked", target_is_directory=True)
                        value = json.loads(record.read_text(encoding="utf-8"))
                        value["evidence_items"][0]["source"]["path"] = "linked/receipt.json"
                        record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
                    else:
                        os.symlink(target, original)
                except (OSError, NotImplementedError) as exc:
                    self.skipTest(f"symlink creation unavailable: {exc}")
                result = self.append(root, map_root, record)
                self.assertEqual(result.returncode, 2)
                self.assertIn("EVIDENCE_PATH_UNSAFE", result.stderr)
                self.assertFalse((root / "history").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction coverage")
    def test_windows_junction_is_rejected_without_persistence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            target = root / "ordinary"
            target.mkdir()
            (root / "receipt.json").replace(target / "receipt.json")
            junction = root / "linked"
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                text=True,
                capture_output=True,
                check=False,
            )
            if created.returncode != 0:
                self.skipTest(created.stderr or created.stdout)
            value = json.loads(record.read_text(encoding="utf-8"))
            value["evidence_items"][0]["source"]["path"] = "linked/receipt.json"
            record.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            result = self.append(root, map_root, record)
            self.assertEqual(result.returncode, 2)
            self.assertIn("EVIDENCE_PATH_UNSAFE", result.stderr)
            self.assertFalse((root / "history").exists())

    def test_report_failure_keeps_one_record_and_rerender_recovers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            map_root, record = self.helper.prepare(root)
            blocked_reports = root / "blocked-reports"
            blocked_reports.write_text("not a directory\n", encoding="utf-8")
            history = root / "history"
            result = self.append(
                root,
                map_root,
                record,
                history=history,
                reports=blocked_reports,
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("REPORT_WRITE_FAILED", result.stderr)
            records = list(history.glob("*.json"))
            self.assertEqual(len(records), 1)
            persisted = json.loads(records[0].read_text(encoding="utf-8"))
            self.assertEqual(persisted["record_kind"], "evidence_bound_audit_record")

            recovered = root / "recovered" / "report.md"
            rerender = self.helper.run_cli(
                root,
                "render",
                "--record",
                str(records[0]),
                "--output",
                str(recovered),
                "--project-root",
                str(root),
            )
            self.assertEqual(rerender.returncode, 0, rerender.stderr)
            self.assertIn("Evidence-bound audit record", recovered.read_text(encoding="utf-8"))
            self.assertEqual(len(list(history.glob("*.json"))), 1)

    def test_pre_hardening_v2_has_explicit_historical_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            _, _, persisted_path = self.persisted_record(root)
            value = json.loads(persisted_path.read_text(encoding="utf-8"))
            value["scan"]["recorder_version"] = "2.0.0"
            value["integrity"].pop("recorder_sha256")
            rewrite_integrity(persisted_path, value)
            result = self.helper.run_cli(root, "render", "--record", str(persisted_path))
            self.assertEqual(result.returncode, 2)
            self.assertIn("LEGACY_V2_CONTRACT_UNBOUND", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
    def test_partial_v2_marker_is_not_misclassified_as_legacy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-release-") as temp:
            root = Path(temp)
            record = root / "partial-v2.json"
            record.write_text(
                json.dumps({"schema_version": "2.0", "record_kind": "wrong"}) + "\n",
                encoding="utf-8",
            )
            result = self.helper.run_cli(root, "render", "--record", str(record))
            self.assertEqual(result.returncode, 2)
            self.assertIn("RECORD_INTEGRITY_MISMATCH", result.stderr)
            self.assertNotIn("LEGACY_RECORD_UNBOUND", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

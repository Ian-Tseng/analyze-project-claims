from __future__ import annotations

import concurrent.futures
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "analyze-project-claims"
RECORDER = SKILL_ROOT / "scripts" / "record_scan.py"


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class EvidenceBoundScanOperationalTests(unittest.TestCase):
    def run_cli(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RECORDER), *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )

    def prepare(self, root: Path, *, map_id: str = "component-map-0123456789ab") -> tuple[Path, Path]:
        artifact = root / "receipt.json"
        artifact.write_text('{"status":"passed"}\n', encoding="utf-8")
        map_root = root / ".claim-audit" / "component-map"
        value = {
            "schema_version": "1.0",
            "map_id": map_id,
            "map_state": "accepted",
            "skill_name": "analyze-project-claims",
            "skill_sha256": hashlib.sha256((SKILL_ROOT / "SKILL.md").read_bytes()).hexdigest(),
            "components": [
                {
                    "component_id": "validation",
                    "component_type": "artifact",
                    "elements": [
                        {
                            "element_id": "receipt",
                            "target": "persisted validation receipt",
                            "relation_type": "validates",
                            "evidence_locators": [],
                        }
                    ],
                }
            ],
        }
        value["integrity"] = {"canonical_payload_sha256": canonical_sha256(value)}
        map_root.mkdir(parents=True)
        (map_root / "accepted-map.json").write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )
        record = {
            "schema_version": "2.0",
            "objective": "Check the persisted validation status.",
            "scope": ["receipt.json"],
            "authority": ["persisted validation receipt"],
            "evidence_items": [
                {
                    "evidence_id": "validation-receipt",
                    "source": {"kind": "file", "path": "receipt.json"},
                    "locator": {"kind": "json_pointer", "value": "/status"},
                    "method": "executed_test",
                    "observed_summary": "The persisted receipt reports passed.",
                }
            ],
            "claims": [
                {
                    "claim_id": "validation-passed",
                    "statement": "The persisted validation receipt reports passed.",
                    "element_ref": {"component_id": "validation", "element_id": "receipt"},
                    "material": True,
                    "status": "supported",
                    "rationale": "The claim is bounded to the selected receipt field.",
                }
            ],
            "bindings": [
                {
                    "claim_id": "validation-passed",
                    "evidence_id": "validation-receipt",
                    "role": "supports",
                }
            ],
            "limitations": [],
            "summary": {
                "strongest_safe_claim_id": "validation-passed",
                "claim_boundary_ids": [],
                "no_supported_claim": False,
            },
            "unresolved_uncertainties": [],
        }
        input_path = root / "input.json"
        input_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return map_root, input_path

    def append(self, root: Path, map_root: Path, record: Path, history: Path) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            root,
            "append",
            "--record",
            str(record),
            "--map-root",
            str(map_root),
            "--project-root",
            str(root),
            "--log-dir",
            str(history),
        )

    def test_help_leads_with_v2_subcommands(self) -> None:
        result = self.run_cli(ROOT, "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("evidence-bound", result.stdout)
        self.assertIn("preflight", result.stdout)
        self.assertIn("draft-v2", result.stdout)

    def test_semantically_invalid_map_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-ops-") as temp:
            root = Path(temp)
            map_root, record = self.prepare(root, map_id="accepted-map")
            result = self.run_cli(
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
            self.assertIn("MAP_NOT_ACCEPTED", result.stderr)

    def test_v2_verify_requires_context_instead_of_overclaiming(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-ops-") as temp:
            root = Path(temp)
            map_root, record = self.prepare(root)
            append = self.append(root, map_root, record, root / "history")
            self.assertEqual(append.returncode, 0, append.stderr)
            persisted = Path(json.loads(append.stdout)["log"])
            verify = self.run_cli(root, "verify", "--record", str(persisted))
            self.assertEqual(verify.returncode, 2)
            self.assertIn("VERIFY_CONTEXT_REQUIRED", verify.stderr)

    def test_concurrent_appends_commit_two_distinct_complete_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="evidence-bound-ops-") as temp:
            root = Path(temp)
            map_root, record = self.prepare(root)
            history = root / "history"
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(self.append, root, map_root, record, history)
                    for _ in range(2)
                ]
                results = [future.result() for future in futures]
            self.assertEqual([result.returncode for result in results], [0, 0])
            paths = sorted(history.glob("*.json"))
            self.assertEqual(len(paths), 2)
            records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
            self.assertEqual(len({value["scan"]["scan_id"] for value in records}), 2)
            self.assertTrue(
                all(value["integrity"]["canonical_payload_sha256"] for value in records)
            )


if __name__ == "__main__":
    unittest.main()

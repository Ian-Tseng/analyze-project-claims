import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "analyze-project-claims" / "scripts"
SKILL_ROOT = ROOT / "skills" / "analyze-project-claims"
CLI = SCRIPTS / "skill_quality_loop.py"
sys.path.insert(0, str(SCRIPTS))

from _internal.skill_quality import attempt_contract  # noqa: E402
from _internal.skill_quality.contract import QualityError  # noqa: E402


class EvaluationManifestTests(unittest.TestCase):
    @staticmethod
    def package(version: str, digest: str) -> dict[str, object]:
        return {
            "owner": "Ian-Tseng",
            "repository": "example-producer",
            "skill": "example-producer",
            "version": version,
            "package_digest_sha256": digest,
        }

    def manifest(self, *, pinned: bool = True) -> dict[str, object]:
        return attempt_contract.create_evaluation_manifest(
            evaluation_id="quality-eval-001",
            problem_signature_sha256="1" * 64,
            baseline_package=self.package("1.0.0", "a" * 64),
            candidate_package=self.package("1.1.0", "b" * 64),
            fixtures=[
                {
                    "capability_id": "managed-skill-quality-loop",
                    "environment_class": "windows-local",
                    "fixture_id": "receipt-handoff-001",
                    "fixture_digest_sha256": "c" * 64,
                    "invariant_id": "portable-explicit-consume",
                    "producer_repository": "example-producer",
                    "quality_signal": "claim_evidence_gap",
                    "taxonomy_id": "skill-quality-pilot-v1",
                }
            ],
            environment={
                "platform_id": "windows-x86_64",
                "runner_image_digest_sha256": "d" * 64,
                "dependency_lock_digest_sha256": "e" * 64,
            },
            model={
                "provider": "openai",
                "model": "pinned-evaluator",
                "parameters_digest_sha256": "f" * 64,
                "pinned": pinned,
            },
            rules={
                "ruleset_id": "quality-gate-v1",
                "ruleset_digest_sha256": "2" * 64,
                "repetitions": 3,
                "minimum_receipt_count": 10,
                "maximum_receipt_count": 20,
                "minimum_baseline_reproducibility_basis_points": 8000,
                "maximum_false_cluster_basis_points": 500,
                "minimum_improvement_basis_points": 500,
                "maximum_regression_basis_points": 100,
            },
            created_at=datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc),
        )

    def test_manifest_round_trip_is_closed_and_ready_when_model_is_pinned(self) -> None:
        manifest = self.manifest()
        self.assertEqual(attempt_contract.validate_evaluation_manifest(manifest), manifest)
        self.assertEqual(attempt_contract.manifest_digest(manifest), manifest["manifest_digest_sha256"])
        self.assertEqual(attempt_contract.evaluation_readiness(manifest), "READY")

    def test_manifest_digest_tampering_is_rejected(self) -> None:
        manifest = self.manifest()
        manifest["rules"]["repetitions"] = 4
        with self.assertRaisesRegex(QualityError, "EVALUATION_DIGEST_MISMATCH"):
            attempt_contract.validate_evaluation_manifest(manifest)

    def test_manifest_rejects_duplicate_receipt_digests(self) -> None:
        manifest = self.result_manifest()
        manifest["fixtures"][1]["fixture_digest_sha256"] = manifest["fixtures"][0][
            "fixture_digest_sha256"
        ]
        manifest["manifest_digest_sha256"] = attempt_contract.manifest_digest(manifest)
        with self.assertRaisesRegex(QualityError, "distinct receipts"):
            attempt_contract.validate_evaluation_manifest(manifest)

    def test_manifest_fixture_binds_frozen_taxonomy_dimensions(self) -> None:
        fixture = self.manifest()["fixtures"][0]
        self.assertEqual(set(fixture), attempt_contract.FIXTURE_KEYS)
        self.assertIn(fixture["quality_signal"], attempt_contract.PILOT_QUALITY_SIGNALS)

    def test_unpinned_model_is_explicitly_inconclusive(self) -> None:
        manifest = self.manifest(pinned=False)
        self.assertEqual(attempt_contract.evaluation_readiness(manifest), "INCONCLUSIVE")

    def test_unpinned_result_is_inconclusive_without_a_failed_gate(self) -> None:
        _manifest, result = self.result(pinned=False)
        self.assertEqual(
            result["classification"],
            {"status": "INCONCLUSIVE", "reason_codes": ["MODEL_UNPINNED"]},
        )

    def test_unknown_fields_are_rejected_even_with_recomputed_digest(self) -> None:
        manifest = self.manifest()
        manifest["notes"] = "free-form project text"
        manifest["manifest_digest_sha256"] = attempt_contract.manifest_digest(manifest)
        with self.assertRaisesRegex(QualityError, "EVALUATION_SCHEMA_VIOLATION"):
            attempt_contract.validate_evaluation_manifest(manifest)

    def test_packaged_synthetic_pilot_is_valid_but_inconclusive(self) -> None:
        path = ROOT / "evaluation" / "quality-loop-pilot" / "synthetic-evaluation-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(attempt_contract.evaluation_readiness(manifest), "INCONCLUSIVE")

    def result_manifest(self, *, pinned: bool = True) -> dict[str, object]:
        manifest = self.manifest(pinned=pinned)
        fixture_template = manifest["fixtures"][0]
        manifest["fixtures"] = [
            {
                **fixture_template,
                "fixture_id": f"receipt-handoff-{index:03d}",
                "fixture_digest_sha256": f"{index:064x}",
            }
            for index in range(1, 11)
        ]
        manifest["manifest_digest_sha256"] = attempt_contract.manifest_digest(manifest)
        return attempt_contract.validate_evaluation_manifest(manifest)

    @staticmethod
    def result_rows(manifest: dict[str, object]) -> list[dict[str, object]]:
        return [
            {
                "fixture_id": fixture["fixture_id"],
                "fixture_digest_sha256": fixture["fixture_digest_sha256"],
                "baseline_replay_matches": 3,
                "baseline_replay_total": 3,
                "problem_cluster_correct": True,
                "owner_disposition": "accepted",
                "owner_authoring_seconds": 120,
                "baseline_score_basis_points": 7000,
                "candidate_score_basis_points": 7600,
                "maximum_regression_basis_points": 0,
                "unauthorized_outbound_actions": 0,
            }
            for fixture in manifest["fixtures"]
        ]

    def result(self, *, pinned: bool = True) -> tuple[dict[str, object], dict[str, object]]:
        manifest = self.result_manifest(pinned=pinned)
        result = attempt_contract.create_evaluation_result(
            manifest=manifest,
            fixture_results=self.result_rows(manifest),
            executed_at=datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc),
        )
        return manifest, result

    def test_manifest_freezes_all_pilot_thresholds(self) -> None:
        rules = self.manifest()["rules"]
        self.assertEqual(rules["minimum_receipt_count"], 10)
        self.assertEqual(rules["maximum_receipt_count"], 20)
        self.assertEqual(rules["minimum_baseline_reproducibility_basis_points"], 8000)
        self.assertEqual(rules["maximum_false_cluster_basis_points"], 500)

    def test_result_round_trip_is_digest_bound_and_passes_frozen_gates(self) -> None:
        manifest, result = self.result()
        self.assertEqual(attempt_contract.validate_evaluation_result(manifest, result), result)
        self.assertEqual(result["classification"], {"status": "PASS", "reason_codes": []})
        self.assertEqual(attempt_contract.result_digest(result), result["result_digest_sha256"])

    def test_receipt_count_gate_uses_distinct_frozen_receipts(self) -> None:
        manifest = self.manifest()
        result = attempt_contract.create_evaluation_result(
            manifest=manifest,
            fixture_results=self.result_rows(manifest),
            executed_at=datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(result["summary"]["receipt_count"], 1)
        self.assertEqual(
            result["classification"],
            {"status": "INCONCLUSIVE", "reason_codes": ["RECEIPT_COUNT_OUT_OF_RANGE"]},
        )

    def test_empty_result_rows_fail_with_a_typed_error(self) -> None:
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_SCHEMA_VIOLATION"):
            attempt_contract.create_evaluation_result(
                manifest=self.result_manifest(),
                fixture_results=[],
                executed_at=datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc),
            )

    def test_each_frozen_quality_gate_can_fail_independently(self) -> None:
        cases = {
            "BASELINE_REPRODUCIBILITY_BELOW_THRESHOLD": lambda rows: [
                row.update(baseline_replay_matches=2) for row in rows
            ],
            "FALSE_CLUSTER_RATE_ABOVE_THRESHOLD": lambda rows: rows[0].update(
                problem_cluster_correct=False
            ),
            "PRIMARY_IMPROVEMENT_BELOW_THRESHOLD": lambda rows: [
                row.update(candidate_score_basis_points=7000) for row in rows
            ],
            "REGRESSION_ABOVE_THRESHOLD": lambda rows: rows[0].update(
                maximum_regression_basis_points=200
            ),
        }
        for reason, mutate in cases.items():
            with self.subTest(reason=reason):
                manifest = self.result_manifest()
                rows = self.result_rows(manifest)
                mutate(rows)
                result = attempt_contract.create_evaluation_result(
                    manifest=manifest,
                    fixture_results=rows,
                    executed_at=datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc),
                )
                self.assertEqual(result["classification"]["status"], "FAIL")
                self.assertIn(reason, result["classification"]["reason_codes"])

    def test_result_rejects_binding_summary_and_time_mismatches(self) -> None:
        manifest, result = self.result()
        result["manifest_digest_sha256"] = "9" * 64
        result["result_digest_sha256"] = attempt_contract.result_digest(result)
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_MANIFEST_MISMATCH"):
            attempt_contract.validate_evaluation_result(manifest, result)

        manifest, result = self.result()
        result["summary"]["receipt_count"] = 9
        result["result_digest_sha256"] = attempt_contract.result_digest(result)
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_SUMMARY_MISMATCH"):
            attempt_contract.validate_evaluation_result(manifest, result)

        manifest, result = self.result()
        result["executed_at_utc"] = "2026-08-27T23:59:59Z"
        result["result_digest_sha256"] = attempt_contract.result_digest(result)
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_TIME_MISMATCH"):
            attempt_contract.validate_evaluation_result(manifest, result)

    def test_result_requires_exact_manifest_fixture_coverage(self) -> None:
        manifest, result = self.result()
        result["fixture_results"].pop()
        result["result_digest_sha256"] = attempt_contract.result_digest(result)
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_FIXTURE_MISMATCH"):
            attempt_contract.validate_evaluation_result(manifest, result)

    def test_result_classification_is_recomputed_not_trusted(self) -> None:
        manifest, result = self.result()
        result["classification"] = {
            "status": "FAIL",
            "reason_codes": ["PRIMARY_IMPROVEMENT_BELOW_THRESHOLD"],
        }
        result["result_digest_sha256"] = attempt_contract.result_digest(result)
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_CLASSIFICATION_MISMATCH"):
            attempt_contract.validate_evaluation_result(manifest, result)

    def test_observed_failure_dominates_unpinned_inconclusive_model(self) -> None:
        manifest = self.result_manifest(pinned=False)
        rows = self.result_rows(manifest)
        rows[0]["unauthorized_outbound_actions"] = 1
        result = attempt_contract.create_evaluation_result(
            manifest=manifest,
            fixture_results=rows,
            executed_at=datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(result["classification"]["status"], "FAIL")
        self.assertEqual(
            result["classification"]["reason_codes"],
            ["MODEL_UNPINNED", "UNAUTHORIZED_OUTBOUND_ACTION"],
        )

    def test_result_rejects_unknown_content_even_with_recomputed_digest(self) -> None:
        manifest, result = self.result()
        result["notes"] = "free-form project content"
        result["result_digest_sha256"] = attempt_contract.result_digest(result)
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_SCHEMA_VIOLATION"):
            attempt_contract.validate_evaluation_result(manifest, result)

    def test_packaged_result_schema_is_closed_and_discoverable(self) -> None:
        result_schema = json.loads(
            (SKILL_ROOT / "references" / "skill-quality-evaluation-result.schema.json").read_text(
                encoding="utf-8"
            )
        )
        manifest_schema = json.loads(
            (SKILL_ROOT / "references" / "skill-quality-evaluation-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(result_schema["additionalProperties"])
        self.assertEqual(set(result_schema["required"]), attempt_contract.RESULT_TOP_KEYS)
        self.assertEqual(
            set(result_schema["$defs"]["fixture_result"]["required"]),
            attempt_contract.RESULT_FIXTURE_KEYS,
        )
        self.assertEqual(
            set(result_schema["$defs"]["summary"]["required"]),
            attempt_contract.SUMMARY_KEYS,
        )
        self.assertEqual(
            set(manifest_schema["$defs"]["rules"]["required"]),
            attempt_contract.RULE_KEYS,
        )
        self.assertEqual(
            set(manifest_schema["$defs"]["fixture"]["required"]),
            attempt_contract.FIXTURE_KEYS,
        )

    def test_cli_validates_exact_manifest_and_result_without_state_or_network(self) -> None:
        manifest, result = self.result()
        with tempfile.TemporaryDirectory(prefix="skill-quality-evaluation-") as temp:
            root = Path(temp)
            manifest_path = root / "manifest.json"
            result_path = root / "result.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result_path.write_text(json.dumps(result), encoding="utf-8")
            state_path = root / "state"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--format",
                    "json",
                    "--state-dir",
                    str(state_path),
                    "evaluation-validate",
                    "--manifest",
                    str(manifest_path),
                    "--result",
                    str(result_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertFalse(state_path.exists())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout)
        self.assertEqual(output["status"], "EVALUATION_RESULT_VALID")
        self.assertEqual(output["classification"], "PASS")
        self.assertEqual(output["outbound"], "NONE")

    def test_cli_missing_evaluation_input_returns_typed_safe_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="skill-quality-evaluation-missing-") as temp:
            root = Path(temp)
            state_path = root / "state"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "--format",
                    "json",
                    "--state-dir",
                    str(state_path),
                    "evaluation-validate",
                    "--manifest",
                    str(root / "missing-manifest.json"),
                    "--result",
                    str(root / "missing-result.json"),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertFalse(state_path.exists())
        self.assertNotEqual(completed.returncode, 0)
        output = json.loads(completed.stdout)
        self.assertEqual(output["code"], "EVALUATION_INPUT_INVALID")
        self.assertIn("no network endpoint", output["safety"])

    def test_result_repetition_count_must_match_frozen_manifest(self) -> None:
        manifest, result = self.result()
        result["fixture_results"][0]["baseline_replay_total"] = 2
        result["fixture_results"][0]["baseline_replay_matches"] = 2
        result["summary"] = attempt_contract._result_summary(result["fixture_results"])
        result["classification"] = attempt_contract._result_classification(manifest, result["summary"])
        result["result_digest_sha256"] = attempt_contract.result_digest(result)
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_REPETITION_MISMATCH"):
            attempt_contract.validate_evaluation_result(manifest, result)

    def test_result_digest_tampering_is_rejected(self) -> None:
        manifest, result = self.result()
        result["executed_at_utc"] = "2026-08-28T01:01:00Z"
        with self.assertRaisesRegex(QualityError, "EVALUATION_RESULT_DIGEST_MISMATCH"):
            attempt_contract.validate_evaluation_result(manifest, result)


if __name__ == "__main__":
    unittest.main()

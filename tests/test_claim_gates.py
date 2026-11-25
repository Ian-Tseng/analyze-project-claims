import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "analyze-project-claims" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import claim_gates as cg  # noqa: E402

NOW = "2026-11-25T00:00:00+00:00"


def claims_doc():
    return {
        "claims": [
            {
                "claim_id": "c1",
                "statement": "The evaluation split was produced and consumed by the reported run.",
                "role": "execution_prerequisite",
                "coverage": "direct",
                "objective_ids": ["o1"],
                "criteria": [
                    {"check_id": "split-present", "type": "file_exists", "path": "data/test.jsonl"},
                    {"check_id": "split-rows", "type": "jsonl_count", "path": "data/test.jsonl", "op": "==", "value": 3},
                ],
            },
            {
                "claim_id": "c2",
                "statement": "The candidate beats the baseline by at least 0.02 accuracy on the test split.",
                "role": "result",
                "coverage": "direct",
                "objective_ids": ["o1"],
                "depends_on": ["c1"],
                "criteria": [
                    {"check_id": "beats-baseline", "type": "json_compare",
                     "path": "results/candidate.json", "pointer": "/metrics/accuracy", "op": ">=",
                     "other_path": "results/baseline.json", "other_pointer": "/metrics/accuracy", "margin": 0.02},
                ],
            },
            {
                "claim_id": "c3",
                "statement": "The method generalises to other domains.",
                "role": "hypothesis",
            },
        ]
    }


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def project(root: Path, candidate=0.81, baseline=0.78, rows=3) -> None:
    write(root, "data/test.jsonl", "".join('{"id": %d}\n' % i for i in range(rows)))
    write(root, "results/candidate.json", json.dumps({"metrics": {"accuracy": candidate}}))
    write(root, "results/baseline.json", json.dumps({"metrics": {"accuracy": baseline}}))


def built():
    spec, warnings = cg.build_spec(claims_doc(), claims_path="claims.json", claims_sha256="0" * 64)
    return spec, warnings


def frozen():
    spec, _ = built()
    return cg.freeze_spec(spec, now=NOW, reason=None)[0]


def by_gate(receipt):
    return {g["gate_id"]: g for g in receipt["gates"]}


class BuildTests(unittest.TestCase):
    def test_build_creates_one_gate_per_material_claim_with_roles_and_dependencies(self):
        spec, warnings = built()
        gates = {g["gate_id"]: g for g in spec["gates"]}
        self.assertEqual(list(gates), ["gate:c1", "gate:c2", "gate:c3"])
        self.assertEqual(gates["gate:c2"]["depends_on"], ["gate:c1"])
        self.assertEqual(gates["gate:c1"]["status"], "ready")
        self.assertEqual(gates["gate:c3"]["status"], "needs_criteria")
        self.assertEqual(gates["gate:c3"]["coverage"], "partial")
        self.assertTrue(any("c3: no coverage given" in w for w in warnings))
        self.assertTrue(any("c3: no machine-checkable criteria" in w for w in warnings))
        self.assertIsNone(spec["freeze"])

    def test_build_accepts_v2_scan_record_claims_and_skips_immaterial(self):
        doc = {"claims": [
            {"claim_id": "a", "statement": "x", "element_ref": {"component_id": "k", "element_id": "e"},
             "material": True, "status": "untested", "rationale": "r"},
            {"claim_id": "b", "statement": "y", "element_ref": {"component_id": "k", "element_id": "e"},
             "material": False, "status": "supported", "rationale": "r"},
        ]}
        spec, warnings = cg.build_spec(doc, claims_path="scan.json", claims_sha256="0" * 64)
        self.assertEqual([g["claim_id"] for g in spec["gates"]], ["a"])
        self.assertEqual(spec["gates"][0]["role"], "result")
        self.assertTrue(any("b: skipped" in w for w in warnings))
        self.assertTrue(any("defaulted to 'result'" in w for w in warnings))

    def test_dependency_must_be_execution_prerequisite(self):
        doc = claims_doc()
        doc["claims"][0]["role"] = "hypothesis"
        with self.assertRaisesRegex(cg.GateError, "not an execution_prerequisite"):
            cg.build_spec(doc, claims_path="c", claims_sha256="0" * 64)

    def test_dependency_cycle_is_rejected(self):
        spec, _ = built()
        spec["gates"][0]["depends_on"] = ["gate:c1"]
        with self.assertRaisesRegex(cg.GateError, "cycle"):
            cg.validate_spec(spec)

    def test_invalid_checks_are_rejected(self):
        bad = [
            ({"check_id": "x", "type": "nope", "path": "a"}, "type must be one of"),
            ({"check_id": "x", "type": "file_exists", "path": "/etc/passwd"}, "relative to the project root"),
            ({"check_id": "x", "type": "json_value", "path": "a.json", "pointer": "m", "op": ">=", "value": 1}, "JSON pointer"),
            ({"check_id": "x", "type": "json_value", "path": "a.json", "pointer": "/m", "op": ">=", "value": "1"}, "must be a number"),
            ({"check_id": "x", "type": "sha256", "path": "a", "sha256": "ABC"}, "64 lowercase hex"),
            ({"check_id": "x", "type": "file_exists", "path": "a", "threshold": 1}, "unknown fields"),
        ]
        for check, message in bad:
            with self.subTest(check=check):
                with self.assertRaisesRegex(cg.GateError, message):
                    cg.validate_check(check, "check")


class FreezeTests(unittest.TestCase):
    def test_freeze_is_idempotent_and_changes_require_a_reason(self):
        spec = frozen()
        same, state = cg.freeze_spec(spec, now=NOW, reason=None)
        self.assertEqual(state, "unchanged")
        changed = json.loads(json.dumps(spec))
        changed["gates"][1]["checks"][0]["margin"] = 0.0
        with self.assertRaisesRegex(cg.GateError, "revision-reason"):
            cg.freeze_spec(changed, now=NOW, reason=None)
        revised, state = cg.freeze_spec(changed, now=NOW, reason="Margin agreed with owner on 2026-11-25")
        self.assertEqual(state, "revised")
        self.assertEqual(revised["revisions"][0]["previous_spec_sha256"], spec["freeze"]["spec_sha256"])
        self.assertEqual(revised["freeze"]["spec_sha256"], cg.spec_digest(revised))


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_passing_evidence_suggests_supported_for_direct_gates(self):
        project(self.root)
        receipt = cg.evaluate_spec(frozen(), self.root, now=NOW, exploratory=False)
        gates = by_gate(receipt)
        self.assertEqual(gates["gate:c1"]["outcome"], "PASS")
        self.assertEqual(gates["gate:c2"]["outcome"], "PASS")
        self.assertEqual(gates["gate:c2"]["claim_suggestion"]["suggested_status"], "supported")
        self.assertTrue(gates["gate:c2"]["claim_suggestion"]["review_required"])
        self.assertEqual(gates["gate:c3"]["outcome"], "INCONCLUSIVE")
        self.assertIsNone(gates["gate:c3"]["claim_suggestion"]["suggested_status"])
        self.assertTrue(receipt["preregistered"])
        expected = hashlib.sha256((self.root / "results/candidate.json").read_bytes()).hexdigest()
        self.assertEqual(receipt["evidence_files"]["results/candidate.json"], expected)
        self.assertEqual(receipt["summary"], {"gates": 3, "PASS": 2, "FAIL": 0, "INCONCLUSIVE": 1, "BLOCKED": 0})

    def test_failed_direct_result_suggests_contradicted(self):
        project(self.root, candidate=0.79)
        gates = by_gate(cg.evaluate_spec(frozen(), self.root, now=NOW, exploratory=False))
        self.assertEqual(gates["gate:c2"]["outcome"], "FAIL")
        self.assertEqual(gates["gate:c2"]["claim_suggestion"]["suggested_status"], "contradicted")

    def test_failed_prerequisite_blocks_dependent_gate(self):
        project(self.root, rows=2)
        gates = by_gate(cg.evaluate_spec(frozen(), self.root, now=NOW, exploratory=False))
        self.assertEqual(gates["gate:c1"]["outcome"], "FAIL")
        self.assertEqual(gates["gate:c1"]["blocks"], ["gate:c2"])
        self.assertEqual(gates["gate:c2"]["outcome"], "BLOCKED")
        self.assertEqual(gates["gate:c2"]["checks_outcome"], "PASS")
        self.assertEqual(gates["gate:c2"]["blocked_by"], ["gate:c1"])
        self.assertIsNone(gates["gate:c2"]["claim_suggestion"]["suggested_status"])

    def test_missing_evidence_is_inconclusive_but_failed_check_dominates(self):
        project(self.root)
        (self.root / "results/baseline.json").unlink()
        gates = by_gate(cg.evaluate_spec(frozen(), self.root, now=NOW, exploratory=False))
        self.assertEqual(gates["gate:c2"]["outcome"], "INCONCLUSIVE")
        spec = frozen()
        spec["gates"][1]["checks"].append(
            {"check_id": "cand-floor", "type": "json_value", "path": "results/candidate.json",
             "pointer": "/metrics/accuracy", "op": ">=", "value": 0.9})
        spec = cg.freeze_spec(spec, now=NOW, reason="add absolute floor")[0]
        gates = by_gate(cg.evaluate_spec(spec, self.root, now=NOW, exploratory=False))
        self.assertEqual(gates["gate:c2"]["outcome"], "FAIL")

    def test_partial_coverage_pass_suggests_only_partial_support(self):
        project(self.root)
        spec, _ = built()
        spec["gates"][1]["coverage"] = "partial"
        spec = cg.freeze_spec(spec, now=NOW, reason=None)[0]
        gates = by_gate(cg.evaluate_spec(spec, self.root, now=NOW, exploratory=False))
        self.assertEqual(gates["gate:c2"]["claim_suggestion"]["suggested_status"], "partially_supported")

    def test_unfrozen_or_modified_gates_are_refused_unless_exploratory(self):
        project(self.root)
        spec, _ = built()
        with self.assertRaisesRegex(cg.GateError, "not frozen"):
            cg.evaluate_spec(spec, self.root, now=NOW, exploratory=False)
        receipt = cg.evaluate_spec(spec, self.root, now=NOW, exploratory=True)
        self.assertFalse(receipt["preregistered"])
        self.assertIn("exploratory", by_gate(receipt)["gate:c2"]["claim_suggestion"]["reason"])
        tampered = frozen()
        tampered["gates"][1]["checks"][0]["margin"] = -1
        with self.assertRaisesRegex(cg.GateError, "changed after they were frozen"):
            cg.evaluate_spec(tampered, self.root, now=NOW, exploratory=False)

    def test_paths_outside_project_root_are_not_read(self):
        project(self.root)
        outside = self.root.parent / "outside-secret.json"
        spec, _ = built()
        spec["gates"][2]["checks"] = [{"check_id": "escape", "type": "file_exists", "path": "../outside-secret.json"}]
        spec["gates"][2]["status"] = "ready"
        spec = cg.freeze_spec(spec, now=NOW, reason=None)[0]
        gate = by_gate(cg.evaluate_spec(spec, self.root, now=NOW, exploratory=False))["gate:c3"]
        self.assertEqual(gate["outcome"], "INCONCLUSIVE")
        self.assertIn("outside the project root", gate["checks"][0]["reason"])
        self.assertFalse(outside.exists())

    def test_non_numeric_and_boolean_values_are_inconclusive(self):
        project(self.root)
        write(self.root, "results/candidate.json", json.dumps({"metrics": {"accuracy": True}}))
        gates = by_gate(cg.evaluate_spec(frozen(), self.root, now=NOW, exploratory=False))
        self.assertEqual(gates["gate:c2"]["outcome"], "INCONCLUSIVE")


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cg.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_build_freeze_evaluate_round_trip_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project(root, candidate=0.79)
            claims = root / "claims.json"
            claims.write_text(json.dumps(claims_doc()), encoding="utf-8")
            gates = root / "gates.json"
            code, out, _ = self.run_cli("build", "--claims", str(claims), "--output", str(gates))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["needs_criteria"], 1)
            code, _, err = self.run_cli("build", "--claims", str(claims), "--output", str(gates))
            self.assertEqual(code, 2)
            self.assertIn("--force", err)
            code, _, err = self.run_cli("evaluate", "--gates", str(gates), "--project-root", str(root))
            self.assertEqual(code, 2)
            self.assertIn("not frozen", err)
            self.assertEqual(self.run_cli("freeze", "--gates", str(gates), "--timestamp", NOW)[0], 0)
            self.assertEqual(json.loads(self.run_cli("validate", "--gates", str(gates))[1])["frozen"], True)
            receipt = root / "receipt.json"
            code, out, _ = self.run_cli("evaluate", "--gates", str(gates), "--project-root", str(root),
                                        "--output", str(receipt), "--timestamp", NOW)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["FAIL"], 1)
            self.assertEqual(json.loads(receipt.read_text(encoding="utf-8"))["kind"], "claim-gates-receipt")
            self.assertEqual(self.run_cli("evaluate", "--gates", str(gates), "--project-root", str(root),
                                          "--fail-on", "fail")[0], 1)
            project(root)
            self.assertEqual(self.run_cli("evaluate", "--gates", str(gates), "--project-root", str(root),
                                          "--fail-on", "fail")[0], 0)
            self.assertEqual(self.run_cli("evaluate", "--gates", str(gates), "--project-root", str(root),
                                          "--fail-on", "not-pass")[0], 1)

    def test_template_builds_valid_gates(self):
        template = ROOT / "skills" / "analyze-project-claims" / "assets" / "claim-gates-claims.template.json"
        doc = json.loads(template.read_text(encoding="utf-8"))
        spec, _ = cg.build_spec(doc, claims_path="template", claims_sha256="0" * 64)
        self.assertTrue(all(g["status"] == "ready" for g in spec["gates"]))


if __name__ == "__main__":
    unittest.main()

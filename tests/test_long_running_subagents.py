"""Integration contracts for claim-grounded durable subagent orchestration.

Fixtures attest only this test contract; they never represent a real skill run.
"""
import copy
import json
import hashlib
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "analyze-project-claims" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from long_running_controller import Controller, ContractError, read_json


class SubagentModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "evidence.txt").write_text("observed baseline\n", encoding="utf-8")
        self.skill = self.root / "SKILL.md"
        self.skill.write_text("Test fixture reviewer contract, not a real skill.\n", encoding="utf-8")
        self.config = {
            "goal_id": "subagent-fixture", "goal_revision": "1",
            "objective": "Produce reviewed fixture output", "authorization_ref": "fixture",
            "project_root": str(self.root), "evidence": ["evidence.txt"],
            "success_criteria": ["output verified"],
            "actions": [{"id": "build", "instruction": "Produce output",
                         "required_claims": ["C1"], "affected_claims": ["C1"]}],
            "subagent_mode": {
                "authorization_ref": "fixture", "reviewer_sources": [str(self.skill)],
                "claims": [
                    {"id": "C1", "statement": "Baseline holds", "scope": "fixture", "depends_on": []},
                    {"id": "C2", "statement": "Derived output holds", "scope": "fixture", "depends_on": ["C1"]}],
                "reports": [{"id": "summary", "title": "Fixture claims", "claim_ids": ["C1", "C2"]}]}}
        self.controller = Controller(self.root / "state")

    def tearDown(self):
        self.tmp.cleanup()

    def start(self):
        self.controller.init(self.config)
        return self.controller.next()["request"]

    def update(self, request, claim_id, status="supported"):
        evidence = {"path": "evidence.txt", "locator": "line:1",
                    "sha256": request["snapshot"]["files"]["evidence.txt"],
                    "method": "source_inspection",
                    "relation": "context" if status in ("untested", "invalidly specified") else "supports"}
        return {"id": claim_id, "status": status, "evidence": [evidence],
                "limitations": [] if status == "supported" else ["Fixture evidence is incomplete"],
                "rationale": "Inspected the current fixture evidence", "audit_refs": []}

    def result(self, request, **overrides):
        result = {"review_status": "COMPLETE", "decision": "CONTINUE",
                  "snapshot_digest": request["snapshot"]["digest"],
                  "request_digest": request["semantic_digest"],
                  "coverage": "Fixture claims and their dependent report",
                  "cleared_actions": ["build"], "next_action": "build",
                  "skill_invocation": {"skill": "analyze-project-claims",
                                       "contract_digest": request["reviewer_contract"]["digest"]},
                  "claim_updates": [self.update(request, cid) for cid in request["required_claim_updates"]]}
        result.update(overrides)
        return result

    def finish_review(self, request, **overrides):
        result = self.result(request, **overrides)
        self.controller.finish(request["token"], result)
        return result

    def dispatch_worker(self):
        self.finish_review(self.start())
        return self.controller.next()["request"]

    def report_files(self):
        pointer = read_json(self.root / "state" / "reports" / "current.json")
        directory = Path(pointer["directory"])
        if not directory.is_absolute():
            candidates = [self.root / "state" / directory, self.root / "state" / "reports" / directory]
            directory = next((p for p in candidates if p.is_dir()), candidates[0])
        return pointer, directory

    def test_initial_review_contains_pinned_contract_and_all_unreviewed_claims(self):
        request = self.start()
        self.assertEqual(request["role"], "claims_reviewer")
        self.assertEqual(set(request["required_claim_updates"]), {"C1", "C2"})
        self.assertTrue(request["reviewer_contract"]["files"])
        self.assertTrue(request["reviewer_contract"]["digest"])
        self.assertEqual(request["working_claims"]["C1"]["status"], "untested")
        self.assertEqual(request["working_claims"]["C1"]["evidence"], [])

    def test_work_review_and_report_cycle_requires_review_before_completion(self):
        worker = self.dispatch_worker()
        self.assertEqual(worker["role"], "worker")
        self.controller.finish(worker["token"], {"status": "done", "summary": "Fixture output generated", "evidence_refs": ["evidence.txt"]})
        state = self.controller.status()
        self.assertEqual(set(state["claim_dirty"]), {"C1", "C2"})
        self.assertFalse(state["complete"])
        request = self.controller.next()["request"]
        self.assertEqual(request["role"], "claims_reviewer")
        self.finish_review(request, cleared_actions=[], next_action=None, goal_complete=True,
                           verified_criteria=["output verified"], evidence_refs=["evidence.txt"])
        self.assertEqual(self.controller.next()["status"], "COMPLETE")
        self.assertEqual(self.controller.status()["claim_dirty"], [])
        pointer, directory = self.report_files()
        self.assertTrue(pointer["revision"])
        self.assertEqual(read_json(directory / "claims.json")["working_claims"]["C2"]["status"], "supported")
        self.assertIn("C1", (directory / "summary.md").read_text(encoding="utf-8"))

    def test_missing_required_action_fields_are_rejected(self):
        for field in ("required_claims", "affected_claims"):
            with self.subTest(field=field):
                config = copy.deepcopy(self.config)
                del config["actions"][0][field]
                with self.assertRaises(ContractError):
                    Controller(self.root / field).init(config)

    def test_premise_free_action_needs_reason_and_affected_claims(self):
        self.config["actions"][0]["required_claims"] = []
        with self.assertRaises(ContractError):
            self.controller.init(self.config)
        self.config["actions"][0]["premise_free_reason"] = "Collect initial evidence"
        self.controller.init(self.config)

    def test_empty_affected_claims_are_rejected(self):
        self.config["actions"][0]["affected_claims"] = []
        with self.assertRaises(ContractError):
            self.controller.init(self.config)

    def test_review_cannot_be_disabled(self):
        self.config["actions"][0]["requires_review"] = False
        with self.assertRaises(ContractError):
            self.controller.init(self.config)

    def test_missing_claim_dependency_unknown_ids_and_cycles_are_rejected(self):
        for mutation in ("unknown_requirement", "unknown_affected", "cycle"):
            with self.subTest(mutation=mutation):
                config = copy.deepcopy(self.config)
                if mutation == "unknown_requirement":
                    config["actions"][0]["required_claims"] = ["missing"]
                elif mutation == "unknown_affected":
                    config["actions"][0]["affected_claims"] = ["missing"]
                else:
                    config["subagent_mode"]["claims"][0]["depends_on"] = ["C2"]
                with self.assertRaises(ContractError):
                    Controller(self.root / mutation).init(config)

    def test_review_requires_skill_attestation_and_affected_closure(self):
        request = self.start()
        for field in ("skill_invocation", "claim_updates"):
            with self.subTest(field=field):
                result = self.result(request)
                del result[field]
                with self.assertRaises(ContractError):
                    self.controller.finish(request["token"], result)
        with self.assertRaises(ContractError):
            self.finish_review(request, claim_updates=[self.update(request, "C1")])
        wrong = self.result(request)
        wrong["skill_invocation"]["contract_digest"] = "not-current"
        with self.assertRaises(ContractError):
            self.controller.finish(request["token"], wrong)

    def test_supported_premise_required_for_worker_clearance(self):
        request = self.start()
        updates = [self.update(request, cid, "untested") for cid in ("C1", "C2")]
        with self.assertRaises(ContractError):
            self.finish_review(request, claim_updates=updates)
        self.assertEqual(self.controller.status()["clearances"], {})

    def test_evidence_hash_and_relation_are_checked(self):
        request = self.start()
        for mutation in ("hash", "not_tested", "contradicts", "no_support"):
            with self.subTest(mutation=mutation):
                result = self.result(request)
                evidence = result["claim_updates"][0]["evidence"][0]
                if mutation == "hash":
                    evidence["sha256"] = "0" * 64
                elif mutation == "not_tested":
                    evidence["method"] = "not_tested"
                elif mutation == "contradicts":
                    result["claim_updates"][0]["evidence"].append(dict(evidence, relation="contradicts"))
                else:
                    evidence["relation"] = "context"
                with self.assertRaises(ContractError):
                    self.controller.finish(request["token"], result)

    def test_non_supported_claim_requires_explicit_limitation(self):
        request = self.start()
        updates = [self.update(request, cid, "untested") for cid in ("C1", "C2")]
        updates[0]["limitations"] = []
        with self.assertRaises(ContractError):
            self.finish_review(request, claim_updates=updates, cleared_actions=[], next_action=None)

    def test_downgraded_premise_prevents_dependent_supported_claim(self):
        request = self.start()
        updates = [self.update(request, "C1", "contradicted"), self.update(request, "C2")]
        updates[0]["evidence"][0]["relation"] = "contradicts"
        with self.assertRaises(ContractError):
            self.finish_review(request, claim_updates=updates, cleared_actions=[], next_action=None)
        updates[1] = self.update(request, "C2", "untested")
        self.finish_review(request, claim_updates=updates, cleared_actions=[], next_action=None)
        self.assertNotEqual(self.controller.status()["working_claims"]["C2"]["status"], "supported")

    def test_worker_cannot_submit_claim_promotions(self):
        worker = self.dispatch_worker()
        with self.assertRaises(ContractError):
            self.controller.finish(worker["token"], {"status": "done", "claim_updates": [{"id": "C1", "status": "supported"}]})
        self.assertIsNotNone(self.controller.status()["pending"])

    def test_worker_affected_claims_extend_declared_scope(self):
        self.config["subagent_mode"]["claims"].append(
            {"id": "C3", "statement": "Independent fixture fact", "scope": "fixture", "depends_on": []})
        worker = self.dispatch_worker()
        self.controller.finish(worker["token"], {"status": "done", "affected_claims": ["C3"]})
        self.assertEqual(set(self.controller.status()["claim_dirty"]), {"C1", "C2", "C3"})

    def test_worker_unknown_affected_claim_is_rejected(self):
        worker = self.dispatch_worker()
        with self.assertRaises(ContractError):
            self.controller.finish(worker["token"], {"status": "done", "affected_claims": ["unknown"]})

    def test_failed_and_uncertain_workers_still_trigger_claim_review(self):
        for outcome in ("failed", "uncertain"):
            with self.subTest(outcome=outcome):
                controller = Controller(self.root / outcome)
                previous = self.controller
                self.controller = controller
                try:
                    worker = self.dispatch_worker()
                    controller.finish(worker["token"], {"status": outcome})
                    request = controller.next()["request"]
                    self.assertEqual(request["role"], "claims_reviewer")
                    self.assertEqual(set(request["required_claim_updates"]), {"C1", "C2"})
                finally:
                    self.controller = previous

    def test_evidence_drift_reopens_all_claims_and_stales_clearance(self):
        self.finish_review(self.start())
        (self.root / "evidence.txt").write_text("new contradictory observation\n", encoding="utf-8")
        request = self.controller.next()["request"]
        self.assertEqual(request["role"], "claims_reviewer")
        self.assertEqual(set(request["required_claim_updates"]), {"C1", "C2"})
        self.assertEqual(self.controller.status()["clearances"], {})

    def test_contract_drift_reopens_claims_and_rejects_old_attestation(self):
        request = self.start()
        old = self.result(request)
        self.skill.write_text("Updated test-only reviewer contract\n", encoding="utf-8")
        self.assertEqual(self.controller.finish(request["token"], old)["status"], "STALE_REVIEW")
        self.assertEqual(self.controller.status()["clearances"], {})
        self.assertEqual(self.controller.status()["working_claims"]["C1"]["status"], "untested")
        fresh = self.controller.next()["request"]
        self.assertNotEqual(fresh["reviewer_contract"]["digest"], request["reviewer_contract"]["digest"])
        self.assertEqual(set(fresh["required_claim_updates"]), {"C1", "C2"})

    def test_agent_binding_restart_pause_and_duplicate_receipt(self):
        request = self.start()
        self.controller.bind_agent(request["token"], "fixture-reviewer")
        self.controller.bind_agent(request["token"], "fixture-reviewer")
        with self.assertRaises(ContractError):
            self.controller.bind_agent(request["token"], "different-reviewer")
        restarted = Controller(self.root / "state")
        pending = restarted.next()
        self.assertEqual(pending["status"], "IN_FLIGHT")
        self.assertIn("fixture-reviewer", json.dumps(pending))
        restarted.control("paused", "Fixture user pause")
        result = self.finish_review(request)
        self.assertEqual(restarted.next()["status"], "PAUSED")
        self.assertEqual(restarted.finish(request["token"], result)["status"], "ALREADY_RECORDED")
        restarted.control("active", "Fixture user resume")
        self.assertEqual(restarted.next()["request"]["role"], "worker")

    def test_reports_regenerate_from_journal_without_claim_mutation(self):
        self.finish_review(self.start())
        expected = copy.deepcopy(self.controller.status()["working_claims"])
        pointer, directory = self.report_files()
        (directory / "summary.md").write_text("corrupt projection", encoding="utf-8")
        (directory / "claims.json").unlink()
        (self.root / "state" / "reports" / "current.json").unlink()
        restored = Controller(self.root / "state").status()
        self.assertEqual(restored["working_claims"], expected)
        fresh_pointer, fresh_directory = self.report_files()
        self.assertEqual(fresh_pointer["revision"], pointer["revision"])
        self.assertEqual(read_json(fresh_directory / "claims.json")["working_claims"], expected)
        self.assertNotEqual((fresh_directory / "summary.md").read_text(encoding="utf-8"), "corrupt projection")

    def test_plan_revision_requires_no_pending_and_invalidates_claim_review(self):
        request = self.start()
        with self.assertRaises(ContractError):
            self.controller.revise("2", "Revised fixture objective", ["output verified"], "fixture user")
        self.finish_review(request)
        self.controller.revise("2", "Revised fixture objective", ["output verified"], "fixture user")
        fresh = self.controller.next()["request"]
        self.assertEqual(fresh["role"], "claims_reviewer")
        self.assertEqual(set(fresh["required_claim_updates"]), {"C1", "C2"})
        self.assertEqual(self.controller.status()["clearances"], {})

    def test_untested_and_invalid_claims_cannot_assert_evidential_support(self):
        request = self.start()
        for status in ("untested", "invalidly specified"):
            for relation in ("supports", "contradicts"):
                with self.subTest(status=status, relation=relation):
                    updates = [self.update(request, cid, status) for cid in ("C1", "C2")]
                    updates[0]["evidence"][0]["relation"] = relation
                    with self.assertRaises(ContractError):
                        self.finish_review(request, claim_updates=updates, cleared_actions=[], next_action=None)

    def test_counterevidence_removal_requires_explicit_disposition(self):
        request = self.start()
        updates = [self.update(request, "C1", "contradicted"), self.update(request, "C2", "untested")]
        updates[0]["evidence"][0]["relation"] = "contradicts"
        old_link = copy.deepcopy(updates[0]["evidence"][0])
        self.finish_review(request, claim_updates=updates, cleared_actions=[], next_action=None)
        (self.root / "evidence.txt").write_text("corrected fixture observation\n", encoding="utf-8")
        fresh = self.controller.next()["request"]
        with self.assertRaises(ContractError):
            self.finish_review(fresh)
        result = self.result(fresh)
        result["claim_updates"][0]["superseded_evidence"] = [
            {"evidence": old_link, "reason": "Fixture observation corrected at evidence.txt line 1; previous contradiction retained in journal"}]
        self.controller.finish(fresh["token"], result)
        self.assertEqual(self.controller.status()["working_claims"]["C1"]["status"], "supported")

    def test_failed_reviews_do_not_release_premise_free_work(self):
        self.config["actions"][0].update(required_claims=[], premise_free_reason="Collect baseline")
        request = self.start()
        for _ in range(2):
            self.finish_review(request, review_status="FAILED", decision="HOLD_DEPENDENT_ACTION", cleared_actions=[], next_action=None)
            item = self.controller.next()
            request = item.get("request")
        self.assertEqual(item["status"], "WAITING")
        self.assertEqual(self.controller.status()["actions"]["build"], "pending")

    def test_report_write_failure_recovers_committed_work_without_replay(self):
        worker = self.dispatch_worker()
        result = {"status": "done", "summary": "Fixture action already executed"}
        with patch("subagent_mode._atomic_bytes", side_effect=OSError("fixture report disk failure")):
            with self.assertRaises(OSError):
                self.controller.finish(worker["token"], result)
        restarted = Controller(self.root / "state")
        self.assertEqual(restarted.status()["actions"]["build"], "done")
        self.assertIsNone(restarted.status()["pending"])
        self.assertEqual(restarted.finish(worker["token"], result)["status"], "ALREADY_RECORDED")
        self.assertEqual(restarted.next()["request"]["role"], "claims_reviewer")
        _, directory = self.report_files()
        self.assertTrue((directory / "claims.json").is_file())

    def test_cli_child_process_lifecycle(self):
        script = SCRIPTS / "long_running_controller.py"
        def cli(*args):
            child = subprocess.run([sys.executable, str(script), "--state", str(self.root / "state"), *args],
                                   capture_output=True, text=True, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(child.returncode, 0, child.stderr)
            return json.loads(child.stdout)
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps(self.config), encoding="utf-8")
        cli("init", "--config", str(config_path))
        request = cli("next")["request"]
        result_path = self.root / "result.json"
        result_path.write_text(json.dumps(self.result(request)), encoding="utf-8")
        cli("finish", "--token", request["token"], "--result", str(result_path))
        worker = cli("next")["request"]
        self.assertEqual(worker["role"], "worker")
        result_path.write_text(json.dumps({"status": "done"}), encoding="utf-8")
        cli("finish", "--token", worker["token"], "--result", str(result_path))
        request = cli("next")["request"]
        result_path.write_text(json.dumps(self.result(request, cleared_actions=[], next_action=None,
            goal_complete=True, verified_criteria=["output verified"], evidence_refs=["evidence.txt"])), encoding="utf-8")
        cli("finish", "--token", request["token"], "--result", str(result_path))
        self.assertEqual(cli("next")["status"], "COMPLETE")

    def test_command_runner_with_explicit_synthetic_read_only_reviewer(self):
        # This adapter exercises transport only. Its marker is a test fixture,
        # not authenticated proof that a real agent invoked the installed skill.
        adapter = self.root / "synthetic_reviewer.py"
        adapter.write_text('''import json, sys
from pathlib import Path
request = json.load(sys.stdin)
assert Path("evidence.txt").read_text().startswith("observed baseline")
finished = request.get("last_work") is not None
updates = [{"id": cid, "status": "supported", "limitations": [],
    "rationale": "Synthetic fixture observed baseline text", "audit_refs": [],
    "evidence": [{"path": "evidence.txt", "locator": "line:1",
        "sha256": request["snapshot"]["files"]["evidence.txt"],
        "method": "source_inspection", "relation": "supports"}]}
    for cid in request["required_claim_updates"]]
result = {"review_status": "COMPLETE", "decision": "CONTINUE",
    "snapshot_digest": request["snapshot"]["digest"], "request_digest": request["semantic_digest"],
    "coverage": "Synthetic local fixture only", "cleared_actions": [] if finished else ["build"],
    "next_action": None if finished else "build", "claim_updates": updates,
    "skill_invocation": {"skill": "analyze-project-claims",
        "contract_digest": request["reviewer_contract"]["digest"]}}
if finished:
    result.update(goal_complete=True, verified_criteria=["output verified"], evidence_refs=["evidence.txt"])
print(json.dumps(result))
''', encoding="utf-8")
        before = (self.root / "evidence.txt").read_bytes()
        self.config["reviewer_command"] = [sys.executable, str(adapter)]
        self.config["subagent_mode"]["reviewer_sources"].append(str(adapter))
        self.config["actions"][0]["command"] = [sys.executable, "-c", "print('synthetic fixture action')"]
        self.controller.init(self.config)
        self.assertEqual(self.controller.run(execute=True)["status"], "COMPLETE")
        self.assertEqual((self.root / "evidence.txt").read_bytes(), before)
        self.assertEqual(len(list((self.root / "state" / "outputs").glob("*.stdout"))), 3)


class CopiedPackageLifecycleTests(unittest.TestCase):
    """Portable CLI transport with synthetic review receipts, never a live AI review."""

    def test_packaged_contract_pins_canonical_controller_despite_adjacent_decoy(self):
        with tempfile.TemporaryDirectory(prefix="claims-contract-") as temporary:
            package = Path(temporary)
            for name in ("long_running_controller.py", "subagent_mode.py"):
                shutil.copy2(SCRIPTS / name, package / name)
            canonical = package / "long_running_controller.py"
            decoy = package / "controller.py"
            decoy.write_text("# Stale legacy filename: not the executed package entrypoint.\n", encoding="utf-8")
            contract = package / "synthetic-reviewer.md"
            contract.write_text("Synthetic contract identity test only.\n", encoding="utf-8")
            probe = package / "probe.py"
            probe.write_text(
                "import json, sys\nimport long_running_controller as runtime\n"
                "print(json.dumps(runtime.subagent_mode.reviewer_snapshot("
                "{'subagent_mode': {'reviewer_sources': [sys.argv[1]]}})))\n",
                encoding="utf-8")
            child = subprocess.run(
                [sys.executable, "-E", "-s", str(probe), str(contract)],
                cwd=package, text=True, capture_output=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(child.returncode, 0, child.stderr)
            files = json.loads(child.stdout)["files"]
            self.assertIn(str(canonical.resolve()), files)
            self.assertNotIn(str(decoy.resolve()), files)
            self.assertEqual(files[str(canonical.resolve())], hashlib.sha256(canonical.read_bytes()).hexdigest())

    def test_copied_package_completes_review_work_review_and_reports(self):
        with tempfile.TemporaryDirectory(prefix="claims-package-") as temporary:
            root = Path(temporary)
            package = root / "package"
            shutil.copytree(SCRIPTS.parent, package,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            project = root / "project"
            project.mkdir()
            state = project / "state"
            script = package / "scripts" / "long_running_controller.py"
            evidence = project / "evidence.txt"
            evidence.write_text("baseline: 7\n", encoding="utf-8")
            contract = project / "synthetic-reviewer.md"
            contract.write_text("Synthetic test contract; no real AI or skill invocation.\n", encoding="utf-8")
            config = {
                "goal_id": "copied-package-fixture", "goal_revision": "1",
                "objective": "Verify copied package fixture lifecycle",
                "authorization_ref": "Synthetic test authorization only",
                "project_root": str(project), "evidence": ["evidence.txt"],
                "success_criteria": ["fixture output verified"],
                "actions": [{"id": "build", "instruction": "Append squared output",
                             "required_claims": ["C1"], "affected_claims": ["C2"]}],
                "subagent_mode": {
                    "authorization_ref": "Synthetic delegation fixture",
                    "reviewer_sources": [str(contract)],
                    "claims": [
                        {"id": "C1", "statement": "Input equals seven", "scope": "fixture", "depends_on": []},
                        {"id": "C2", "statement": "Output equals forty-nine", "scope": "fixture", "depends_on": ["C1"]}],
                    "reports": [{"id": "summary", "title": "Synthetic fixture claims", "claim_ids": ["C1", "C2"]}]}}
            config_path = project / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            def cli(*arguments):
                # -E ignores PYTHONPATH and -s disables user site packages. The
                # copied script directory is the only source of the runtime.
                child = subprocess.run(
                    [sys.executable, "-E", "-s", str(script), "--state", str(state), *arguments],
                    cwd=project, text=True, capture_output=True, timeout=30,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(child.returncode, 0, child.stderr)
                return json.loads(child.stdout)

            def synthetic_review(request, final=False):
                observed = evidence.read_text(encoding="utf-8")
                self.assertIn("baseline: 7", observed)
                if final:
                    self.assertIn("output: 49", observed)
                updates = []
                for claim_id in request["required_claim_updates"]:
                    supported = claim_id == "C1" or final
                    updates.append({
                        "id": claim_id, "status": "supported" if supported else "untested",
                        "evidence": [{"path": "evidence.txt", "locator": "line:2" if claim_id == "C2" and supported else "line:1",
                                      "sha256": request["snapshot"]["files"]["evidence.txt"],
                                      "method": "source_inspection", "relation": "supports" if supported else "context"}],
                        "limitations": ["Synthetic fixture only"] if supported else ["Output not yet produced"],
                        "rationale": "Synthetic reviewer checked fixture text; no real skill invocation",
                        "audit_refs": []})
                result = {
                    "review_status": "COMPLETE", "decision": "CONTINUE",
                    "snapshot_digest": request["snapshot"]["digest"], "request_digest": request["semantic_digest"],
                    "coverage": "Synthetic copied-package fixture; not a native AI review",
                    "cleared_actions": [] if final else ["build"], "next_action": None if final else "build",
                    "skill_invocation": {"skill": "analyze-project-claims", "contract_digest": request["reviewer_contract"]["digest"]},
                    "claim_updates": updates}
                if final:
                    result.update(goal_complete=True, verified_criteria=["fixture output verified"], evidence_refs=["evidence.txt"])
                return result

            def finish(request, result):
                result_file = project / (request["token"] + ".json")
                result_file.write_text(json.dumps(result), encoding="utf-8")
                return cli("finish", "--token", request["token"], "--result", str(result_file))

            cli("init", "--config", str(config_path))
            initial = cli("next")["request"]
            self.assertEqual(initial["role"], "claims_reviewer")
            pinned_files = initial["reviewer_contract"]["files"]
            self.assertIn(str(script.resolve()), pinned_files)
            self.assertIn(str((package / "scripts" / "subagent_mode.py").resolve()), pinned_files)
            finish(initial, synthetic_review(initial))
            worker = cli("next")["request"]
            self.assertEqual(worker["role"], "worker")
            cli("bind-agent", "--token", worker["token"], "--agent-id", "synthetic-worker-fixture")
            self.assertEqual(cli("check", "--token", worker["token"])["status"], "READY")
            evidence.write_text("baseline: 7\noutput: 49\n", encoding="utf-8")
            finish(worker, {"status": "done", "summary": "Synthetic worker appended squared output"})
            interim = cli("status")
            self.assertFalse(interim["complete"])
            self.assertEqual(interim["working_claims"]["C2"]["status"], "untested")
            review = cli("next")["request"]
            self.assertEqual(review["role"], "claims_reviewer")
            finish(review, synthetic_review(review, final=True))
            self.assertEqual(cli("next")["status"], "COMPLETE")
            current = cli("status")
            self.assertTrue(current["freshness"]["completion_current"])
            self.assertEqual(current["claim_dirty"], [])
            pointer = json.loads((state / "reports" / "current.json").read_text(encoding="utf-8"))
            directory = Path(pointer["directory"])
            if not directory.is_absolute():
                directory = next(path for path in (state / directory, state / "reports" / directory) if path.is_dir())
            claims = json.loads((directory / "claims.json").read_text(encoding="utf-8"))
            self.assertEqual(claims["working_claims"]["C2"]["status"], "supported")
            self.assertEqual(claims["working_claims"]["C2"]["evidence"][0]["sha256"], hashlib.sha256(evidence.read_bytes()).hexdigest())
            report = (directory / "summary.md").read_text(encoding="utf-8")
            self.assertIn("Synthetic fixture only", report)
            self.assertIn("C2", report)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from nomination_contract_support import canonical, check_schema, digest, load
from nomination_runtime_fixtures import refresh_component_map

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "evidence-nomination" / "v1"
GOLDEN = CONTRACT / "golden"
SCHEMAS = ("gap-request", "bundle", "selection", "claim-candidate", "component-candidate")


class EvidenceNominationContractTests(unittest.TestCase):
    def test_five_closed_schemas_and_reference_resolution(self):
        self.assertEqual({p.stem.removesuffix(".schema") for p in CONTRACT.glob("*.schema.json")}, set(SCHEMAS))
        for name in SCHEMAS:
            schema = load(CONTRACT / f"{name}.schema.json")
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(schema["type"], "object")
            check_schema(load(GOLDEN / f"{name}.json"), CONTRACT / f"{name}.schema.json")

    def test_all_golden_variants_and_templates_validate(self):
        manifest = load(GOLDEN / "manifest.json")
        for item in manifest["artifacts"]:
            with self.subTest(path=item["path"]):
                path = CONTRACT / item["path"]
                check_schema(load(path), CONTRACT / item["schema"])
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item["sha256"])
                self.assertEqual(path.read_bytes(), canonical(load(path)) + b"\n")

    def test_unrecognized_fields_and_mixed_target_refused(self):
        for name in SCHEMAS:
            value = load(GOLDEN / f"{name}.json")
            value["accepted_state_changed"] = True
            with self.subTest(schema=name), self.assertRaises(ValueError):
                check_schema(value, CONTRACT / f"{name}.schema.json")
        request = load(GOLDEN / "gap-request.json")
        request["target"]["claim_id"] = "unrequested-claim"
        with self.assertRaises(ValueError):
            check_schema(request, CONTRACT / "gap-request.schema.json")

    def test_numeric_caps_and_boolean_integer_confusion(self):
        schema = CONTRACT / "gap-request.schema.json"
        original = load(GOLDEN / "gap-request.json")
        caps = {"max_files": 2500, "max_total_bytes": 67108864, "max_file_bytes": 1048576,
                "max_requirements": 8, "max_raw_matches": 5000, "max_per_requirement": 5,
                "max_nominations": 20, "max_excerpt_bytes": 2048, "max_range_bytes": 65536,
                "timeout_seconds": 10}
        self.assertEqual(original["resource_policy"], caps)
        for key, cap in caps.items():
            for bad in (0, cap + 1, True):
                value = copy.deepcopy(original)
                value["resource_policy"][key] = bad
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    check_schema(value, schema)

    def test_paths_and_empty_query_refused(self):
        original = load(GOLDEN / "gap-request.json")
        for path in ("../secret", "/etc", "C:/private", "a\\b", "a//b", "./a", "a/../b", "a:stream", "a/", "a/./b", "a\nname"):
            value = copy.deepcopy(original)
            value["allowed_roots"] = [path]
            with self.subTest(path=path), self.assertRaises(ValueError):
                check_schema(value, CONTRACT / "gap-request.schema.json")
        value = copy.deepcopy(original)
        value["requirements"][0]["all_terms"] = []
        value["requirements"][0]["any_terms"] = []
        with self.assertRaises(ValueError):
            check_schema(value, CONTRACT / "gap-request.schema.json")

    def test_candidate_payloads_match_existing_authorities(self):
        refs = ROOT / "skills" / "analyze-project-claims" / "references"
        for name, existing in (("claim-candidate", "scan-record-v2.schema.json"),
                               ("component-candidate", "component-map-observation.schema.json")):
            value = load(GOLDEN / f"{name}.json")
            check_schema(value["payload"], refs / existing)
            bad = copy.deepcopy(value)
            bad["payload"]["accepted"] = True
            with self.assertRaises(ValueError):
                check_schema(bad, CONTRACT / f"{name}.schema.json")

    def test_identity_and_provenance_golden_vectors(self):
        vectors = load(GOLDEN / "identity-vectors.json")
        for item in vectors["canonical"]:
            self.assertEqual(canonical(item["value"]).hex(), item["utf8_hex"])
            self.assertEqual(digest(item["value"]), item["sha256"])
        for filename in ("bundle.json", "claim-bundle.json", "zero-bundle.json", "partial-bundle.json"):
            bundle = load(GOLDEN / filename)
            payload = {k: v for k, v in bundle.items() if k not in ("bundle_id", "canonical_payload_sha256")}
            self.assertEqual(digest(payload), bundle["canonical_payload_sha256"])
            self.assertEqual(bundle["bundle_id"], "nomination-" + digest(payload))
            for source in bundle["corpus"]:
                raw = (GOLDEN / "project" / source["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), source["sha256"])
                self.assertEqual(len(raw), source["size_bytes"])
            for nomination in bundle["nominations"]:
                raw = (GOLDEN / "project" / nomination["path"]).read_bytes()
                selected = raw[nomination["byte_start"]:nomination["byte_end"]]
                self.assertEqual(hashlib.sha256(selected).hexdigest(), nomination["range_sha256"])
                self.assertEqual(nomination["excerpt"].encode("utf-8"), selected[:len(nomination["excerpt"].encode("utf-8"))])
                self.assertEqual(nomination["nomination_id"], "hit-" + digest({k:v for k,v in nomination.items() if k != "nomination_id"}))
        for prefix in ("", "claim-"):
            bundle = load(GOLDEN / f"{prefix}bundle.json")
            selection_file = GOLDEN / f"{prefix}selection.json"
            selection = load(selection_file)
            candidate = load(GOLDEN / ("claim-candidate.json" if prefix else "component-candidate.json"))
            envelope = candidate["provenance"]
            self.assertEqual(selection["bundle"], envelope["bundle"])
            self.assertEqual(envelope["bundle"]["bundle_id"], bundle["bundle_id"])
            self.assertEqual(envelope["bundle"]["canonical_payload_sha256"], bundle["canonical_payload_sha256"])
            self.assertEqual(envelope["selection_sha256"], hashlib.sha256(selection_file.read_bytes()).hexdigest())
            self.assertEqual(envelope["map"], bundle["request"]["map"])
            self.assertEqual(envelope["target"], bundle["request"]["target"])
            self.assertEqual(envelope["selected_nomination_ids"], sorted(item["nomination_id"] for item in selection["selections"]))
            payload = {k:v for k,v in candidate.items() if k not in ("candidate_id", "canonical_payload_sha256")}
            self.assertEqual(candidate["canonical_payload_sha256"], digest(payload))
            self.assertEqual(candidate["candidate_id"], "candidate-" + digest(payload))

    def test_schema_and_code_identity_are_not_self_referential(self):
        bundle = load(GOLDEN / "bundle.json")
        finder = bundle["finder"]
        self.assertEqual(finder["implementation_kind"], "contract_fixture")
        self.assertEqual(finder["contract_sha256"], hashlib.sha256((CONTRACT / "CONTRACT.md").read_bytes()).hexdigest())
        self.assertEqual(finder["code_sha256"], hashlib.sha256((GOLDEN / "fixture-producer.txt").read_bytes()).hexdigest())
        for item in load(GOLDEN / "identity-vectors.json")["native_schemas"]:
            self.assertEqual(item["sha256"], hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest())
        for item in finder["schemas"]:
            self.assertEqual(item["sha256"], hashlib.sha256((CONTRACT / item["path"]).read_bytes()).hexdigest())
        original = {k:v for k,v in bundle.items() if k not in ("bundle_id", "canonical_payload_sha256")}
        for field in ("code_sha256", "contract_sha256"):
            altered = copy.deepcopy(original)
            altered["finder"][field] = "f" * 64
            self.assertNotEqual(digest(original), digest(altered))

    def test_fixture_map_and_claim_target_bind_real_fixture_bytes(self):
        map_path = GOLDEN / "project" / "map" / "accepted-map.json"
        value = load(map_path)
        payload = {k:v for k,v in value.items() if k != "integrity"}
        self.assertEqual(value["integrity"]["canonical_payload_sha256"], digest(payload))
        request = load(GOLDEN / "claim-gap-request.json")
        self.assertEqual(request["map"], {"map_id":value["map_id"], "canonical_payload_sha256":digest(payload), "file_sha256":hashlib.sha256(map_path.read_bytes()).hexdigest()})
        record_path = GOLDEN / "project" / "record.json"
        record = load(record_path)
        self.assertEqual(request["target"]["record_sha256"], hashlib.sha256(record_path.read_bytes()).hexdigest())
        self.assertEqual(request["target"]["scan_id"], record["scan"]["scan_id"])
        claim = next(c for c in record["claims"] if c["claim_id"] == request["target"]["claim_id"])
        self.assertEqual(request["target"]["claim_digest"], digest(claim["statement"]))
        self.assertEqual(request["target"]["element_ref"], claim["element_ref"])
        reformatted = json.dumps(value, indent=4).encode("utf-8")
        self.assertNotEqual(hashlib.sha256(reformatted).hexdigest(), request["map"]["file_sha256"])
        self.assertEqual(digest(json.loads(reformatted)), digest(value))

    def test_query_rank_and_completeness_vectors(self):
        for filename in ("bundle.json", "claim-bundle.json", "zero-bundle.json", "partial-bundle.json"):
            bundle = load(GOLDEN / filename)
            queries = {q["query_id"]:q["requirement"] for q in bundle["queries"]}
            for qid, requirement in queries.items():
                self.assertEqual(qid, "query-" + digest(requirement))
            nominations = bundle["nominations"]
            self.assertEqual(nominations, sorted(nominations, key=lambda n:(-n["score"], n["path"], n["byte_start"], n["byte_end"], n["query_id"])))
            for n in nominations:
                raw = (GOLDEN / "project" / n["path"]).read_bytes()
                selected = raw[n["byte_start"]:n["byte_end"]].decode("utf-8")
                source = next(c for c in bundle["corpus"] if c["path"] == n["path"])
                self.assertEqual(n["source_sha256"], source["sha256"])
                self.assertLessEqual(len(n["excerpt"].encode("utf-8")), bundle["request"]["resource_policy"]["max_excerpt_bytes"])
                for match in n["matches"]:
                    requirement = queries[match["query_id"]]
                    self.assertEqual(match["requirement_id"], requirement["requirement_id"])
                    self.assertEqual(match["requested_role"], requirement["requested_role"])
                    self.assertTrue(all(t in selected for t in requirement["all_terms"]))
                    self.assertTrue(not requirement["any_terms"] or any(t in selected for t in requirement["any_terms"]))
                    self.assertFalse(any(t in selected for t in requirement["exclude_terms"]))
                    self.assertEqual(match["score"], 100*len(requirement["all_terms"]) + 10*sum(t in selected for t in requirement["any_terms"]))
            self.assertEqual(bundle["completeness"] == "partial", bool(bundle["truncations"]))
        self.assertEqual(load(GOLDEN / "zero-bundle.json")["nominations"], [])
        self.assertEqual(len(load(GOLDEN / "partial-bundle.json")["nominations"]), 1)

    def test_draft_template_and_reviewer_payload_preservation(self):
        draft = load(CONTRACT / "templates" / "selection-empty.json")
        check_schema(draft, CONTRACT / "selection.schema.json")
        self.assertEqual(draft["selections"], [])
        self.assertIsNone(draft["reviewer_input"])
        claim_selection = load(GOLDEN / "claim-selection.json")
        self.assertEqual(load(GOLDEN / "claim-candidate.json")["payload"], claim_selection["reviewer_input"]["record_input"])
        selection = load(GOLDEN / "selection.json")
        original = selection["reviewer_input"]["observation"]
        expected = copy.deepcopy(original)
        expected["components"][0]["elements"][0]["evidence"].append({"source":"evidence/support.txt", "locator":"lines:1-1", "observed":selection["selections"][0]["observed_summary"]})
        self.assertEqual(load(GOLDEN / "component-candidate.json")["payload"], expected)
        for name in ("claim-candidate", "component-candidate"):
            candidate = load(GOLDEN / f"{name}.json")
            candidate["provenance"]["selected_nomination_ids"] = []
            with self.assertRaises(ValueError):
                check_schema(candidate, CONTRACT / f"{name}.schema.json")

    def test_native_validator_accepts_payload_and_marks_historical_recorder_stale(self):
        script = ROOT / "skills" / "analyze-project-claims" / "scripts" / "record_scan.py"
        with tempfile.TemporaryDirectory(prefix="nomination-contract-") as temporary:
            project = Path(temporary).resolve() / "project"
            shutil.copytree(GOLDEN / "project", project)
            refresh_component_map(project, load(GOLDEN / "gap-request.json"))
            record_path = project / "candidate-payload.json"
            record_path.write_bytes(canonical(load(GOLDEN / "claim-candidate.json")["payload"]) + b"\n")
            before = (project / "map" / "accepted-map.json").read_bytes()
            for action, record in (("validate", record_path), ("verify", project / "record.json")):
                result = subprocess.run([sys.executable, str(script), action, "--record", str(record), "--project-root", str(project), "--map-root", str(project / "map")], capture_output=True, text=True, encoding="utf-8", timeout=60)
                # Frozen v0.9.0 record bytes are historical after T3 changes the
                # recorder/engine. Validation of the native input still passes;
                # current-code verification must refuse the old code identity.
                self.assertEqual(result.returncode, 0 if action == "validate" else 3, result.stdout + result.stderr)
                if action == "verify":
                    self.assertIn("RECORDER_IDENTITY_MISMATCH", result.stdout + result.stderr)
            self.assertEqual((project / "map" / "accepted-map.json").read_bytes(), before)

    def test_raw_byte_identity_distinguishes_line_endings(self):
        raw = (GOLDEN / "project" / "evidence" / "counter.txt").read_bytes()
        self.assertIn(b"\r\n", raw)
        self.assertNotEqual(hashlib.sha256(raw).digest(), hashlib.sha256(raw.replace(b"\r\n", b"\n")).digest())


if __name__ == "__main__":
    unittest.main()

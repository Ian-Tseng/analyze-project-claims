"""Reviewed selection adapters. They create sidecars, never invoke native commands."""
from __future__ import annotations

import copy
from pathlib import Path

from .common import MAX_JSON_BYTES, SKILL, Deadline, Schemas, canonical, digest, fail, parse_json, sha
from .engine import Context, read_bundle, verify
from .filesystem import absolute, safe_read


def bundle_ref(raw, bundle):
    return {"bundle_id": bundle["bundle_id"], "canonical_payload_sha256": bundle["canonical_payload_sha256"], "file_sha256": sha(raw)}


def sidecar(path, bundle_path, protected=()):
    path = absolute(path)
    if path.parent != absolute(bundle_path).parent or path in {absolute(p) for p in (bundle_path, *protected)}:
        fail(2, "safety_refusal", "sidecar_scope")
    return path


def claim_payload(review, selected, hits, target):
    payload = copy.deepcopy(review["record_input"])
    evidence = {item["evidence_id"]: item for item in payload["evidence_items"]}
    if len(evidence) != len(payload["evidence_items"]):
        fail(2, "invalid_input", "duplicate_evidence_id")
    claims = [c for c in payload["claims"] if c["claim_id"] == target["claim_id"]]
    if len(claims) != 1 or digest(claims[0]["statement"]) != target["claim_digest"] or claims[0]["element_ref"] != target["element_ref"]:
        fail(2, "invalid_input", "claim_target_mismatch")
    ids = set()
    for item in selected:
        eid = item.get("evidence_id")
        if not eid or eid in ids:
            fail(2, "selection_incomplete", "selected_evidence_id")
        ids.add(eid)
        hit = hits[item["nomination_id"]]
        expected = {"evidence_id": eid, "source": {"kind": "file", "path": hit["path"]},
                    "locator": {"kind": "line_range", "start": hit["line_start"], "end": hit["line_end"]},
                    "method": "inspected", "observed_summary": item["observed_summary"]}
        if evidence.get(eid) != expected:
            fail(2, "invalid_input", "selected_evidence_mismatch")
        binding = {"claim_id": target["claim_id"], "evidence_id": eid, "role": item["evidence_role"]}
        if binding not in payload["bindings"]:
            fail(2, "selection_incomplete", "selected_role_binding")
    return payload


def component_payload(review, selected, hits, target, accepted):
    payload = copy.deepcopy(review["observation"])
    # Only locator insertion is generated. Full reviewer structure must retain
    # every accepted component/element and its exact type/target.
    def structure(components):
        result = {}
        for component in components:
            cid = component["component_id"]
            if cid in result:
                fail(2, "invalid_input", "duplicate_component")
            elements = {e["element_id"]: e["target"] for e in component["elements"]}
            if len(elements) != len(component["elements"]):
                fail(2, "invalid_input", "duplicate_element")
            result[cid] = (component["component_type"], elements)
        return result
    if structure(payload["components"]) != structure(accepted["components"]):
        fail(2, "invalid_input", "component_structure_mismatch")
    ref = target["element_ref"]
    element = next(e for c in payload["components"] if c["component_id"] == ref["component_id"]
                   for e in c["elements"] if e["element_id"] == ref["element_id"])
    for item in selected:
        if "evidence_id" in item:
            fail(2, "invalid_input", "component_evidence_id")
        hit = hits[item["nomination_id"]]
        evidence = {"source": hit["path"], "locator": f"lines:{hit['line_start']}-{hit['line_end']}", "observed": item["observed_summary"]}
        if evidence not in element["evidence"]:
            element["evidence"].append(evidence)
    return payload


def compile_review(bundle_path, selection_path, project, map_root, record=None):
    _, initial = read_bundle(bundle_path)
    deadline = Deadline(initial["request"]["resource_policy"]["timeout_seconds"])
    raw_bundle, bundle = verify(bundle_path, project, map_root, record, deadline=deadline)
    selection_path = sidecar(selection_path, bundle_path)
    raw_selection = safe_read(selection_path, MAX_JSON_BYTES, deadline)
    selection = parse_json(raw_selection)
    schemas = Schemas()
    schemas.validate(selection, "selection")
    if selection["bundle"] != bundle_ref(raw_bundle, bundle):
        fail(4, "stale_identity", "selection_bundle_identity")
    selected = selection["selections"]
    review = selection["reviewer_input"]
    if not selected or review is None:
        fail(2, "selection_incomplete", "review_required")
    target = bundle["request"]["target"]
    if review["kind"] != target["kind"]:
        fail(2, "invalid_input", "review_target_kind")
    hits = {n["nomination_id"]: n for n in bundle["nominations"]}
    ids = [item["nomination_id"] for item in selected]
    if len(set(ids)) != len(ids) or any(i not in hits for i in ids):
        fail(2, "invalid_input", "selected_nomination_ids")
    ctx = Context(bundle["request"], project, map_root, record_path=record, output=Path(bundle_path).parent, deadline=deadline)
    accepted = parse_json(safe_read(ctx.map_path, MAX_JSON_BYTES, ctx.deadline))
    if target["kind"] == "claim":
        payload = claim_payload(review, selected, hits, target)
    else:
        payload = component_payload(review, selected, hits, target, accepted)
    candidate = {"schema_version": "1.0", "artifact_kind": target["kind"] + "_candidate",
                 "provenance": {"bundle": selection["bundle"], "map": bundle["request"]["map"],
                                "selection_sha256": sha(raw_selection), "target": target,
                                "selected_nomination_ids": sorted(ids)}, "payload": payload}
    identity = digest(candidate)
    candidate.update(candidate_id="candidate-" + identity, canonical_payload_sha256=identity)
    schemas.validate(candidate, target["kind"] + "-candidate")
    # Recheck authority and every admitted source after inspecting reviewer input.
    again_raw, again_bundle = verify(bundle_path, project, map_root, record, deadline=deadline)
    if again_raw != raw_bundle or again_bundle != bundle or safe_read(selection_path, MAX_JSON_BYTES, deadline) != raw_selection:
        fail(4, "stale_identity", "review_input_changed")
    return candidate, bundle


def handoff(candidate_path, bundle_path, selection_path, project, map_root, record=None):
    candidate_path = sidecar(candidate_path, bundle_path, (selection_path,))
    raw = safe_read(candidate_path, MAX_JSON_BYTES)
    candidate = parse_json(raw)
    expected, bundle = compile_review(bundle_path, selection_path, project, map_root, record)
    if candidate != expected:
        fail(4, "tampered_identity", "candidate_provenance_or_payload")
    return candidate, bundle


def native_command(candidate, payload_path, project, map_root):
    kind = candidate["provenance"]["target"]["kind"]
    native = SKILL / "scripts" / ("record_scan.py" if kind == "claim" else "reconcile_component_map.py")
    # argv is display data, never shell text or executable input to this tool.
    args = [str(native), "validate" if kind == "claim" else "reconcile",
            "--record" if kind == "claim" else "--observation", str(payload_path),
            "--project-root", str(absolute(project)), "--map-root", str(absolute(map_root))]
    identity = candidate["provenance"]["map"]
    args += ["--expected-map-id", identity["map_id"],
             "--expected-map-canonical-sha256", identity["canonical_payload_sha256"],
             "--expected-map-file-sha256", identity["file_sha256"],
             "--expected-input-sha256", sha(canonical(candidate["payload"]) + b"\n")]
    return args

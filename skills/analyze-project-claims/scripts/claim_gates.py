#!/usr/bin/env python3
"""Build, freeze and evaluate evidence gates derived from project claims.

A gate states, before results are inspected, which machine-checkable evidence
conditions a claim must meet. Evaluation reads only declared files under the
project root and writes a receipt. Gate outcomes are suggestions for the
claim classification rules in SKILL.md; they never accept a claim, certify an
independent replication or change a project record by themselves.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = 1
KIND = "claim-gates"
RECEIPT_KIND = "claim-gates-receipt"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_CLAIMS = 500
MAX_CHECKS = 64
ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-:.][a-z0-9]+)*$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ROLES = ("execution_prerequisite", "hypothesis", "result")
COVERAGE = ("direct", "partial")
CLAIM_STATUSES = (
    "supported", "partially_supported", "contradicted", "untested",
    "invalidly_specified", "not_applicable",
)
OPS = ("==", "!=", "<", "<=", ">", ">=")
ORDERED_OPS = ("<", "<=", ">", ">=")
CHECK_FIELDS = {
    "file_exists": ({"path"}, set()),
    "sha256": ({"path", "sha256"}, set()),
    "json_value": ({"path", "pointer", "op", "value"}, set()),
    "json_compare": ({"path", "pointer", "op", "other_path", "other_pointer"}, {"margin"}),
    "jsonl_count": ({"path", "op", "value"}, set()),
}
CHECK_COMMON = {"check_id", "type", "description", "required"}
GATE_FIELDS = {
    "gate_id", "claim_id", "statement", "role", "objective_ids", "coverage",
    "depends_on", "checks", "status", "notes",
}
SPEC_FIELDS = {"schema_version", "kind", "source", "gates", "freeze", "revisions"}
CLAIM_FIELDS = {
    "claim_id", "statement", "role", "objective_ids", "coverage", "depends_on",
    "criteria", "material", "status", "rationale", "element_ref", "scope", "notes",
}
LIMITATIONS = [
    "Gate checks test only the declared evidence files and conditions.",
    "A PASS is not human acceptance, independent replication or proof of benefit.",
    "Missing or unreadable evidence is INCONCLUSIVE, not FAIL, except for file_exists checks.",
    "Suggested claim statuses must still be reviewed under the skill's classification rules.",
]


class GateError(ValueError):
    """A claims file, gate specification or check violates the gate contract."""


# ---------------------------------------------------------------- utilities

def _now(override: str | None) -> str:
    if override:
        return override
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path, what: str) -> Any:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise GateError(f"cannot read {what} {path}: {exc.strerror}") from exc
    if size > MAX_JSON_BYTES:
        raise GateError(f"{what} {path} exceeds {MAX_JSON_BYTES} bytes")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise GateError(f"{what} {path} is not valid JSON: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _require_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.match(value) or len(value) > 128:
        raise GateError(f"{field} must be a lowercase id such as 'c1' or 'claim:accuracy' (got {value!r})")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(f"{field} must be a non-empty string")
    return value.strip()


def _id_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise GateError(f"{field} must be a list of ids")
    return [_require_id(item, f"{field}[{i}]") for i, item in enumerate(value)]


def _unknown(value: dict, allowed: set[str], field: str) -> None:
    extra = sorted(set(value) - allowed)
    if extra:
        raise GateError(f"{field} has unknown fields: {', '.join(extra)}")


def gate_id_for(claim_id: str) -> str:
    return f"gate:{claim_id}"


# ------------------------------------------------------------ validation

def validate_check(check: Any, field: str) -> dict:
    if not isinstance(check, dict):
        raise GateError(f"{field} must be an object")
    ctype = check.get("type")
    if ctype not in CHECK_FIELDS:
        raise GateError(f"{field}.type must be one of {', '.join(CHECK_FIELDS)} (got {ctype!r})")
    required, optional = CHECK_FIELDS[ctype]
    _unknown(check, required | optional | CHECK_COMMON, field)
    missing = sorted(required - set(check))
    if missing:
        raise GateError(f"{field} ({ctype}) is missing: {', '.join(missing)}")
    _require_id(check.get("check_id"), f"{field}.check_id")
    for key in ("path", "other_path"):
        if key in check:
            _require_text(check[key], f"{field}.{key}")
            if Path(check[key]).is_absolute() or check[key].startswith(("/", "\\")):
                raise GateError(f"{field}.{key} must be relative to the project root")
    for key in ("pointer", "other_pointer"):
        if key in check and not (isinstance(check[key], str) and (check[key] == "" or check[key].startswith("/"))):
            raise GateError(f"{field}.{key} must be a JSON pointer such as '/metrics/accuracy'")
    if "op" in check and check["op"] not in OPS:
        raise GateError(f"{field}.op must be one of {' '.join(OPS)}")
    if ctype == "sha256" and not (isinstance(check["sha256"], str) and SHA_RE.match(check["sha256"])):
        raise GateError(f"{field}.sha256 must be 64 lowercase hex characters")
    if ctype == "jsonl_count" and not _is_number(check["value"]):
        raise GateError(f"{field}.value must be a number")
    if ctype == "json_value" and check["op"] in ORDERED_OPS and not _is_number(check["value"]):
        raise GateError(f"{field}.value must be a number for op {check['op']}")
    if ctype == "json_compare":
        if check["op"] not in ORDERED_OPS + ("==",):
            raise GateError(f"{field}.op must be an ordered comparison or == for json_compare")
        if "margin" in check and not _is_number(check["margin"]):
            raise GateError(f"{field}.margin must be a number")
    if "required" in check and not isinstance(check["required"], bool):
        raise GateError(f"{field}.required must be true or false")
    if "description" in check:
        _require_text(check["description"], f"{field}.description")
    return check


def validate_spec(spec: Any) -> dict:
    if not isinstance(spec, dict):
        raise GateError("gate specification must be a JSON object")
    _unknown(spec, SPEC_FIELDS, "gate specification")
    if spec.get("kind") != KIND or spec.get("schema_version") != SCHEMA_VERSION:
        raise GateError(f"gate specification must have kind '{KIND}' and schema_version {SCHEMA_VERSION}")
    gates = spec.get("gates")
    if not isinstance(gates, list) or not gates:
        raise GateError("gates must be a non-empty list")
    seen: dict[str, dict] = {}
    for i, gate in enumerate(gates):
        field = f"gates[{i}]"
        if not isinstance(gate, dict):
            raise GateError(f"{field} must be an object")
        _unknown(gate, GATE_FIELDS, field)
        gid = _require_id(gate.get("gate_id"), f"{field}.gate_id")
        if gid in seen:
            raise GateError(f"duplicate gate_id {gid}")
        _require_id(gate.get("claim_id"), f"{field}.claim_id")
        _require_text(gate.get("statement"), f"{field}.statement")
        if gate.get("role") not in ROLES:
            raise GateError(f"{field}.role must be one of {', '.join(ROLES)}")
        if gate.get("coverage") not in COVERAGE:
            raise GateError(f"{field}.coverage must be 'direct' or 'partial'")
        _id_list(gate.get("objective_ids"), f"{field}.objective_ids")
        _id_list(gate.get("depends_on"), f"{field}.depends_on")
        checks = gate.get("checks")
        if not isinstance(checks, list) or len(checks) > MAX_CHECKS:
            raise GateError(f"{field}.checks must be a list of at most {MAX_CHECKS} checks")
        ids = set()
        for j, check in enumerate(checks):
            validate_check(check, f"{field}.checks[{j}]")
            if check["check_id"] in ids:
                raise GateError(f"{field} has duplicate check_id {check['check_id']}")
            ids.add(check["check_id"])
        expected = "ready" if checks else "needs_criteria"
        if gate.get("status") != expected:
            raise GateError(f"{field}.status must be '{expected}' for a gate with {len(checks)} checks")
        seen[gid] = gate
    for gid, gate in seen.items():
        for dep in gate.get("depends_on", []):
            if dep not in seen:
                raise GateError(f"{gid} depends on unknown gate {dep}")
            if seen[dep]["role"] != "execution_prerequisite":
                raise GateError(f"{gid} depends on {dep}, which is not an execution_prerequisite gate")
    _check_acyclic(seen)
    freeze = spec.get("freeze")
    if freeze is not None:
        if not isinstance(freeze, dict) or set(freeze) != {"frozen_at", "spec_sha256"}:
            raise GateError("freeze must be null or {frozen_at, spec_sha256}")
        if not SHA_RE.match(str(freeze["spec_sha256"])):
            raise GateError("freeze.spec_sha256 must be 64 lowercase hex characters")
    if not isinstance(spec.get("revisions", []), list):
        raise GateError("revisions must be a list")
    return spec


def _check_acyclic(gates: dict[str, dict]) -> None:
    state: dict[str, int] = {}

    def visit(gid: str, trail: list[str]) -> None:
        if state.get(gid) == 2:
            return
        if state.get(gid) == 1:
            raise GateError("gate dependencies form a cycle: " + " -> ".join(trail + [gid]))
        state[gid] = 1
        for dep in gates[gid].get("depends_on", []):
            visit(dep, trail + [gid])
        state[gid] = 2

    for gid in gates:
        visit(gid, [])


def spec_digest(spec: dict) -> str:
    """Digest of the gate definitions only; freeze and revision metadata are excluded."""
    return _sha256_bytes(_canonical(spec["gates"]))


# ------------------------------------------------------------------ build

def _claims_from_document(doc: Any) -> list[dict]:
    if isinstance(doc, dict) and isinstance(doc.get("claims"), list):
        return doc["claims"]
    if isinstance(doc, list):
        return doc
    raise GateError("claims file must be a list of claims or an object with a 'claims' list (for example a v2 scan record)")


def build_spec(claims_doc: Any, *, claims_path: str, claims_sha256: str,
               include_immaterial: bool = False) -> tuple[dict, list[str]]:
    claims = _claims_from_document(claims_doc)
    if len(claims) > MAX_CLAIMS:
        raise GateError(f"at most {MAX_CLAIMS} claims are supported")
    warnings: list[str] = []
    gates = []
    by_claim: dict[str, dict] = {}
    for i, claim in enumerate(claims):
        field = f"claims[{i}]"
        if not isinstance(claim, dict):
            raise GateError(f"{field} must be an object")
        _unknown(claim, CLAIM_FIELDS, field)
        cid = _require_id(claim.get("claim_id"), f"{field}.claim_id")
        if cid in by_claim:
            raise GateError(f"duplicate claim_id {cid}")
        if claim.get("material") is False and not include_immaterial:
            warnings.append(f"{cid}: skipped because material is false")
            by_claim[cid] = {}
            continue
        if claim.get("status") is not None and claim["status"] not in CLAIM_STATUSES:
            raise GateError(f"{field}.status must be one of {', '.join(CLAIM_STATUSES)}")
        if claim.get("status") == "invalidly_specified":
            warnings.append(f"{cid}: claim is invalidly specified; fix its population, protocol, metric or comparator before trusting a gate")
        role = claim.get("role")
        if role is None:
            role = "result"
            warnings.append(f"{cid}: no role given; defaulted to 'result' (a link alone does not make a claim an execution prerequisite)")
        elif role not in ROLES:
            raise GateError(f"{field}.role must be one of {', '.join(ROLES)}")
        coverage = claim.get("coverage")
        if coverage is None:
            coverage = "partial"
            warnings.append(f"{cid}: no coverage given; defaulted to 'partial', so a PASS can suggest at most partially_supported")
        elif coverage not in COVERAGE:
            raise GateError(f"{field}.coverage must be 'direct' or 'partial'")
        checks = claim.get("criteria") or []
        if not isinstance(checks, list):
            raise GateError(f"{field}.criteria must be a list of checks")
        checks = [validate_check(copy.deepcopy(c), f"{field}.criteria[{j}]") for j, c in enumerate(checks)]
        if not checks:
            warnings.append(f"{cid}: no machine-checkable criteria; gate created as needs_criteria and will evaluate INCONCLUSIVE")
        gate = {
            "gate_id": gate_id_for(cid),
            "claim_id": cid,
            "statement": _require_text(claim.get("statement"), f"{field}.statement"),
            "role": role,
            "objective_ids": _id_list(claim.get("objective_ids"), f"{field}.objective_ids"),
            "coverage": coverage,
            "depends_on": [gate_id_for(d) for d in _id_list(claim.get("depends_on"), f"{field}.depends_on")],
            "checks": checks,
            "status": "ready" if checks else "needs_criteria",
        }
        if claim.get("notes"):
            gate["notes"] = _require_text(claim["notes"], f"{field}.notes")
        gates.append(gate)
        by_claim[cid] = gate
    if not gates:
        raise GateError("no material claims to build gates from")
    built = {g["gate_id"] for g in gates}
    for gate in gates:
        kept = []
        for dep in gate["depends_on"]:
            if dep in built:
                kept.append(dep)
            else:
                warnings.append(f"{gate['claim_id']}: dependency {dep} has no gate and was dropped")
        gate["depends_on"] = kept
    spec = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "source": {"claims_path": claims_path, "claims_sha256": claims_sha256},
        "gates": gates,
        "freeze": None,
        "revisions": [],
    }
    validate_spec(spec)
    return spec, warnings


# ----------------------------------------------------------------- freeze

def freeze_spec(spec: dict, *, now: str, reason: str | None) -> tuple[dict, str]:
    validate_spec(spec)
    digest = spec_digest(spec)
    frozen = spec.get("freeze")
    if frozen and frozen["spec_sha256"] == digest:
        return spec, "unchanged"
    if frozen and not reason:
        raise GateError(
            "gates changed after they were frozen; re-freeze with --revision-reason explaining the change "
            "(criteria must not be weakened merely to declare success)")
    out = copy.deepcopy(spec)
    if frozen:
        out.setdefault("revisions", []).append({
            "revised_at": now,
            "previous_spec_sha256": frozen["spec_sha256"],
            "new_spec_sha256": digest,
            "reason": _require_text(reason, "revision reason"),
        })
    out["freeze"] = {"frozen_at": now, "spec_sha256": digest}
    return out, "revised" if frozen else "frozen"


# --------------------------------------------------------------- evaluate

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _resolve(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise GateError("path resolves outside the project root") from exc
    return path


def _pointer(doc: Any, pointer: str) -> Any:
    if pointer == "":
        return doc
    node = doc
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            raise KeyError(pointer)
    return node


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]


class _Evidence:
    def __init__(self, root: Path):
        self.root = root
        self.files: dict[str, str | None] = {}
        self._json: dict[str, Any] = {}

    def path(self, rel: str) -> Path:
        path = _resolve(self.root, rel)
        key = path.relative_to(self.root).as_posix()
        if key not in self.files:
            self.files[key] = _sha256_file(path) if path.is_file() else None
        return path

    def json(self, rel: str) -> Any:
        path = self.path(rel)
        key = path.relative_to(self.root).as_posix()
        if key not in self._json:
            if not path.is_file():
                raise FileNotFoundError(rel)
            self._json[key] = _load_json(path, "evidence file")
        return self._json[key]


def run_check(check: dict, ev: _Evidence) -> dict:
    out = {"check_id": check["check_id"], "type": check["type"], "required": check.get("required", True)}
    ctype = check["type"]
    try:
        if ctype == "file_exists":
            ok = ev.path(check["path"]).is_file()
            out.update(outcome="PASS" if ok else "FAIL", observed="present" if ok else "missing")
        elif ctype == "sha256":
            path = ev.path(check["path"])
            if not path.is_file():
                return {**out, "outcome": "INCONCLUSIVE", "reason": "evidence file missing"}
            actual = ev.files[path.relative_to(ev.root).as_posix()]
            out.update(outcome="PASS" if actual == check["sha256"] else "FAIL", observed=actual)
        elif ctype == "json_value":
            observed = _pointer(ev.json(check["path"]), check["pointer"])
            out["observed"] = observed
            if check["op"] in ORDERED_OPS and not _is_number(observed):
                return {**out, "outcome": "INCONCLUSIVE", "reason": "observed value is not a number"}
            out["outcome"] = "PASS" if _compare(observed, check["op"], check["value"]) else "FAIL"
        elif ctype == "json_compare":
            left = _pointer(ev.json(check["path"]), check["pointer"])
            right = _pointer(ev.json(check["other_path"]), check["other_pointer"])
            margin = check.get("margin", 0)
            out.update(observed=left, reference=right, margin=margin)
            if not (_is_number(left) and _is_number(right)):
                return {**out, "outcome": "INCONCLUSIVE", "reason": "compared values are not both numbers"}
            out["outcome"] = "PASS" if _compare(left, check["op"], right + margin) else "FAIL"
        elif ctype == "jsonl_count":
            path = ev.path(check["path"])
            if not path.is_file():
                return {**out, "outcome": "INCONCLUSIVE", "reason": "evidence file missing"}
            with path.open("rb") as handle:
                count = sum(1 for line in handle if line.strip())
            out.update(observed=count, outcome="PASS" if _compare(count, check["op"], check["value"]) else "FAIL")
    except FileNotFoundError:
        out.update(outcome="INCONCLUSIVE", reason="evidence file missing")
    except KeyError:
        out.update(outcome="INCONCLUSIVE", reason="JSON pointer not found in evidence file")
    except GateError as exc:
        out.update(outcome="INCONCLUSIVE", reason=str(exc))
    except TypeError:
        out.update(outcome="INCONCLUSIVE", reason="values cannot be compared")
    return out


def _combine(results: list[dict]) -> str:
    required = [r["outcome"] for r in results if r["required"]]
    if not required:
        return "INCONCLUSIVE"
    if "FAIL" in required:
        return "FAIL"
    if "INCONCLUSIVE" in required:
        return "INCONCLUSIVE"
    return "PASS"


def _suggest(gate: dict, outcome: str, preregistered: bool) -> dict:
    direct = gate["coverage"] == "direct"
    if outcome == "PASS":
        status = "supported" if direct else "partially_supported"
        reason = "all required checks passed" + ("" if direct else " but the gate covers only part of the claim's scope")
    elif outcome == "FAIL" and direct:
        status, reason = "contradicted", "a required check failed on direct same-scope evidence"
    elif outcome == "FAIL":
        status, reason = None, "a required check failed within a narrower scope; review it as counterevidence"
    elif outcome == "BLOCKED":
        status, reason = None, "an execution-prerequisite gate has not passed"
    else:
        status, reason = None, "evidence is missing or incomplete; keep the current status or mark untested"
    if status and not preregistered:
        reason += "; gates were not frozen before evaluation, so treat the result as exploratory"
    return {"suggested_status": status, "review_required": True, "reason": reason}


def evaluate_spec(spec: dict, root: Path, *, now: str, exploratory: bool) -> dict:
    validate_spec(spec)
    root = root.resolve()
    if not root.is_dir():
        raise GateError(f"project root {root} is not a directory")
    digest = spec_digest(spec)
    frozen = spec.get("freeze")
    if frozen is None and not exploratory:
        raise GateError("gates are not frozen; run 'freeze' before looking at results, or pass --exploratory")
    if frozen is not None and frozen["spec_sha256"] != digest:
        raise GateError("gates changed after they were frozen; re-freeze with a revision reason before evaluating")
    preregistered = frozen is not None
    ev = _Evidence(root)
    by_id = {g["gate_id"]: g for g in spec["gates"]}
    outcomes: dict[str, str] = {}
    gate_results: dict[str, dict] = {}

    def evaluate(gid: str) -> str:
        if gid in outcomes:
            return outcomes[gid]
        gate = by_id[gid]
        checks = [run_check(c, ev) for c in gate["checks"]]
        own = _combine(checks)
        blockers = [d for d in gate["depends_on"] if evaluate(d) != "PASS"]
        outcome = "BLOCKED" if blockers else own
        outcomes[gid] = outcome
        gate_results[gid] = {
            "gate_id": gid,
            "claim_id": gate["claim_id"],
            "role": gate["role"],
            "coverage": gate["coverage"],
            "objective_ids": gate["objective_ids"],
            "outcome": outcome,
            "checks_outcome": own,
            "blocked_by": blockers,
            "checks": checks,
            "claim_suggestion": _suggest(gate, outcome, preregistered),
        }
        return outcome

    for gid in by_id:
        evaluate(gid)
    ordered = [gate_results[g["gate_id"]] for g in spec["gates"]]
    for res in ordered:
        if res["role"] == "execution_prerequisite":
            res["blocks"] = [g["gate_id"] for g in spec["gates"]
                             if res["gate_id"] in g["depends_on"] and res["outcome"] != "PASS"]
    counts = {k: sum(1 for r in ordered if r["outcome"] == k) for k in ("PASS", "FAIL", "INCONCLUSIVE", "BLOCKED")}
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        "evaluated_at": now,
        "spec_sha256": digest,
        "preregistered": preregistered,
        "frozen_at": frozen["frozen_at"] if frozen else None,
        "project_root": str(root),
        "summary": {"gates": len(ordered), **counts},
        "gates": ordered,
        "evidence_files": dict(sorted(ev.files.items())),
        "limitations": LIMITATIONS,
    }


# --------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="create a gate specification from a claims file or v2 scan record")
    b.add_argument("--claims", required=True, type=Path)
    b.add_argument("--output", required=True, type=Path)
    b.add_argument("--include-immaterial", action="store_true")
    b.add_argument("--force", action="store_true", help="overwrite an existing output file")

    v = sub.add_parser("validate", help="check a gate specification without reading evidence")
    v.add_argument("--gates", required=True, type=Path)

    f = sub.add_parser("freeze", help="record the gate digest before results are inspected")
    f.add_argument("--gates", required=True, type=Path)
    f.add_argument("--revision-reason")
    f.add_argument("--timestamp")

    e = sub.add_parser("evaluate", help="evaluate gates against evidence under a project root")
    e.add_argument("--gates", required=True, type=Path)
    e.add_argument("--project-root", required=True, type=Path)
    e.add_argument("--output", type=Path, help="write the receipt here (default: print it)")
    e.add_argument("--exploratory", action="store_true", help="allow evaluating unfrozen gates")
    e.add_argument("--fail-on", choices=("never", "fail", "not-pass"), default="never",
                   help="exit 1 when any gate FAILs, or when any gate does not PASS")
    e.add_argument("--timestamp")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            if args.output.exists() and not args.force:
                raise GateError(f"{args.output} exists; pass --force to overwrite it")
            doc = _load_json(args.claims, "claims file")
            spec, warnings = build_spec(
                doc, claims_path=args.claims.as_posix(), claims_sha256=_sha256_file(args.claims),
                include_immaterial=args.include_immaterial)
            _write_json(args.output, spec)
            ready = sum(1 for g in spec["gates"] if g["status"] == "ready")
            print(json.dumps({"status": "built", "output": str(args.output), "gates": len(spec["gates"]),
                              "ready": ready, "needs_criteria": len(spec["gates"]) - ready,
                              "warnings": warnings}, indent=2))
        elif args.command == "validate":
            spec = validate_spec(_load_json(args.gates, "gate specification"))
            print(json.dumps({"status": "valid", "gates": len(spec["gates"]), "spec_sha256": spec_digest(spec),
                              "frozen": spec.get("freeze") is not None}, indent=2))
        elif args.command == "freeze":
            spec = _load_json(args.gates, "gate specification")
            out, state = freeze_spec(spec, now=_now(args.timestamp), reason=args.revision_reason)
            if state != "unchanged":
                _write_json(args.gates, out)
            print(json.dumps({"status": state, **out["freeze"]}, indent=2))
        elif args.command == "evaluate":
            spec = _load_json(args.gates, "gate specification")
            receipt = evaluate_spec(spec, args.project_root, now=_now(args.timestamp), exploratory=args.exploratory)
            if args.output:
                _write_json(args.output, receipt)
                print(json.dumps({"status": "evaluated", "output": str(args.output), **receipt["summary"]}, indent=2))
            else:
                print(json.dumps(receipt, indent=2, ensure_ascii=False))
            s = receipt["summary"]
            if args.fail_on == "fail" and s["FAIL"]:
                return 1
            if args.fail_on == "not-pass" and s["PASS"] != s["gates"]:
                return 1
    except GateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

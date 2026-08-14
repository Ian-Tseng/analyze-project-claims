#!/usr/bin/env python3
"""Validate and interpret product-lifecycle receipts without executing lifecycle actions."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence


PROTOCOL_VERSION = "1.0"
MAX_CYCLES = 3
MAX_INPUT_BYTES = 2 * 1024 * 1024
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
RUN_ID_RE = re.compile(r"plv-[a-z0-9-]{1,64}")
PHASES = (
    "RELEASE_A_INSTALL",
    "RELEASE_A_IDENTITY",
    "RELEASE_A_ACTIVATION",
    "UPDATE_DRY_RUN",
    "RELEASE_B_UPDATE",
    "RELEASE_B_IDENTITY",
    "RELEASE_B_ACTIVATION",
    "REPORT_PREVIEW",
    "ROLLBACK_VERIFIED",
    "ROLLBACK_ACTIVATION",
    "CLEANUP",
)
AGGREGATE_FIELDS = {
    "schema_version", "kind", "protocol_version", "run_id", "plan_digest",
    "verifier", "adapter", "product", "target", "status", "phases",
    "strongest_safe_claim", "limitations", "actions_not_performed",
    "parent_receipt_digest", "iteration", "resume_digest", "receipt_digest",
}
PHASE_FIELDS = {
    "schema_version", "kind", "protocol_version", "run_id", "sequence",
    "phase", "status", "evidence_method", "started_at", "ended_at",
    "summary", "pre_identity", "post_identity", "mutations",
    "network_destinations", "artifacts", "error_code",
    "previous_receipt_digest", "receipt_digest",
}


class ReceiptError(ValueError):
    """A lifecycle evidence artifact violates the consumer contract."""

    def __init__(self, code: str, message: str, fix: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.fix = fix


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def object_digest(value: Mapping[str, object], field: str) -> str:
    payload = copy.deepcopy(dict(value))
    payload.pop(field, None)
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def verify_digest(value: Mapping[str, object], field: str, code: str = "RECEIPT_DIGEST_INVALID") -> str:
    actual = value.get(field)
    expected = object_digest(value, field)
    if not isinstance(actual, str) or actual != expected:
        raise ReceiptError(code, f"{field} does not bind the current artifact.")
    return actual


def _require_text(value: object, field: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ReceiptError("RECEIPT_SCHEMA_INVALID", f"{field} must be bounded non-empty text.")
    return value


def _validate_phase(raw: object, *, run_id: str, sequence: int, previous: str | None) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != PHASE_FIELDS:
        raise ReceiptError("PHASE_SCHEMA_INVALID", f"Phase {sequence} has unknown or missing fields.")
    if raw.get("schema_version") != 1 or raw.get("kind") != "LifecyclePhaseReceipt" or raw.get("protocol_version") != PROTOCOL_VERSION:
        raise ReceiptError("PHASE_SCHEMA_INVALID", f"Phase {sequence} has an unsupported contract.")
    if raw.get("run_id") != run_id or raw.get("sequence") != sequence:
        raise ReceiptError("PHASE_CHAIN_INVALID", f"Phase {sequence} does not match its run or sequence.")
    if raw.get("previous_receipt_digest") != previous:
        raise ReceiptError("PHASE_CHAIN_INVALID", f"Phase {sequence} does not link to the prior receipt.")
    if raw.get("phase") not in PHASES:
        raise ReceiptError("PHASE_CHAIN_INVALID", f"Phase {sequence} is not a declared lifecycle phase.")
    if raw.get("status") not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
        raise ReceiptError("PHASE_SCHEMA_INVALID", f"Phase {sequence} has an invalid status.")
    if raw.get("evidence_method") not in {"executed_test", "schema_validated", "inspected", "not_tested"}:
        raise ReceiptError("PHASE_SCHEMA_INVALID", f"Phase {sequence} has an invalid evidence method.")
    for field in ("started_at", "ended_at", "summary"):
        _require_text(raw.get(field), f"phase[{sequence}].{field}")
    for field in ("pre_identity", "post_identity", "artifacts"):
        if not isinstance(raw.get(field), dict):
            raise ReceiptError("PHASE_SCHEMA_INVALID", f"phase[{sequence}].{field} must be an object.")
    for field, maximum in (("mutations", 32), ("network_destinations", 16)):
        value = raw.get(field)
        if not isinstance(value, list) or len(value) > maximum or any(not isinstance(item, str) for item in value):
            raise ReceiptError("PHASE_SCHEMA_INVALID", f"phase[{sequence}].{field} is invalid.")
    error_code = raw.get("error_code")
    if error_code is not None and (not isinstance(error_code, str) or len(error_code) > 80):
        raise ReceiptError("PHASE_SCHEMA_INVALID", f"phase[{sequence}].error_code is invalid.")
    verify_digest(raw, "receipt_digest", "PHASE_DIGEST_INVALID")
    return copy.deepcopy(raw)


def _validate_receipt(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != AGGREGATE_FIELDS:
        raise ReceiptError("RECEIPT_SCHEMA_INVALID", "Lifecycle receipt has unknown or missing fields.")
    verify_digest(raw, "receipt_digest", "RECEIPT_DIGEST_INVALID")
    if raw.get("schema_version") != 1 or raw.get("kind") != "LifecycleVerificationReceipt" or raw.get("protocol_version") != PROTOCOL_VERSION:
        raise ReceiptError("RECEIPT_SCHEMA_INVALID", "Lifecycle receipt contract is unsupported.")
    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ReceiptError("RECEIPT_SCHEMA_INVALID", "Lifecycle receipt run_id is invalid.")
    for field in ("verifier", "adapter", "product", "target"):
        if not isinstance(raw.get(field), dict):
            raise ReceiptError("RECEIPT_SCHEMA_INVALID", f"{field} must be an object.")
    for field in ("plan_digest", "receipt_digest"):
        if not isinstance(raw.get(field), str) or not DIGEST_RE.fullmatch(str(raw[field])):
            raise ReceiptError("RECEIPT_SCHEMA_INVALID", f"{field} is invalid.")
    phases_raw = raw.get("phases")
    if not isinstance(phases_raw, list) or len(phases_raw) > len(PHASES):
        raise ReceiptError("RECEIPT_SCHEMA_INVALID", "phases must be a bounded lifecycle prefix.")
    phases: list[dict[str, object]] = []
    previous = None
    for sequence, item in enumerate(phases_raw, 1):
        phase = _validate_phase(item, run_id=run_id, sequence=sequence, previous=previous)
        phases.append(phase)
        previous = str(phase["receipt_digest"])
    failures = [index for index, phase in enumerate(phases) if phase["status"] != "PASS"]
    if not failures:
        names = [str(phase["phase"]) for phase in phases]
        if names != list(PHASES[:len(names)]):
            raise ReceiptError("PHASE_CHAIN_INVALID", "Passing phases are not a lifecycle prefix.")
    else:
        first_failure = failures[0]
        prefix_names = [str(phase["phase"]) for phase in phases[:first_failure + 1]]
        if prefix_names != list(PHASES[:len(prefix_names)]):
            raise ReceiptError("PHASE_CHAIN_INVALID", "The lifecycle failed outside the declared phase order.")
        passed_before = {
            str(phase["phase"]) for phase in phases[:first_failure]
            if phase["status"] == "PASS"
        }
        recovery_order = []
        if "ROLLBACK_VERIFIED" not in passed_before:
            recovery_order.append("ROLLBACK_VERIFIED")
        if "ROLLBACK_ACTIVATION" not in passed_before:
            recovery_order.append("ROLLBACK_ACTIVATION")
        recovery_order.append("CLEANUP")
        tail = phases[first_failure + 1:]
        tail_names = [str(phase["phase"]) for phase in tail]
        if tail_names != recovery_order[:len(tail_names)]:
            raise ReceiptError("PHASE_CHAIN_INVALID", "Post-failure phases are not the bounded rollback/cleanup branch.")
        if any(phase["status"] != "PASS" for phase in tail[:-1]):
            raise ReceiptError("PHASE_CHAIN_INVALID", "Only the last recovery phase may be non-passing.")
    status = raw.get("status")
    allowed_statuses = {
        "RELEASE_B_REQUIRED", "CLEANUP_REQUIRED",
        "ROLLBACK_COMPLETE_CLEANUP_REQUIRED", "RECOVERY_REQUIRED",
        "RUN_INTERRUPTED_RECOVERABLE", "COMPLETE", "RECOVERED",
    }
    if status not in allowed_statuses:
        raise ReceiptError("RECEIPT_SCHEMA_INVALID", "Lifecycle receipt status is unsupported.")
    all_pass = all(item["status"] == "PASS" for item in phases)
    if status == "COMPLETE" and (len(phases) != len(PHASES) or not all_pass):
        raise ReceiptError("RECEIPT_STATE_INVALID", "COMPLETE requires every declared phase including cleanup to pass.")
    if status == "CLEANUP_REQUIRED" and (len(phases) != len(PHASES) - 1 or not all_pass):
        raise ReceiptError("RECEIPT_STATE_INVALID", "CLEANUP_REQUIRED requires every pre-cleanup phase to pass.")
    if status == "RELEASE_B_REQUIRED" and (len(phases) != 3 or not all_pass):
        raise ReceiptError("RECEIPT_STATE_INVALID", "RELEASE_B_REQUIRED requires the Release A checkpoint.")
    if status == "RECOVERY_REQUIRED" and (not failures or phases[-1]["status"] == "PASS"):
        raise ReceiptError("RECEIPT_STATE_INVALID", "RECOVERY_REQUIRED requires a terminal non-passing phase.")
    if status == "RUN_INTERRUPTED_RECOVERABLE" and (not all_pass or len(phases) >= len(PHASES)):
        raise ReceiptError("RECEIPT_STATE_INVALID", "Interrupted receipt must end at a passing phase boundary.")
    if status == "ROLLBACK_COMPLETE_CLEANUP_REQUIRED":
        rollback_verified = any(phase["phase"] == "ROLLBACK_VERIFIED" and phase["status"] == "PASS" for phase in phases)
        activation_verified = any(phase["phase"] == "ROLLBACK_ACTIVATION" and phase["status"] == "PASS" for phase in phases)
        if not failures or not rollback_verified or not activation_verified or phases[-1]["phase"] != "ROLLBACK_ACTIVATION" or phases[-1]["status"] != "PASS":
            raise ReceiptError("RECEIPT_STATE_INVALID", "Recovery cleanup requires a passing rollback and restored activation.")
    if status == "RECOVERED":
        rollback_verified = any(phase["phase"] == "ROLLBACK_VERIFIED" and phase["status"] == "PASS" for phase in phases)
        activation_verified = any(phase["phase"] == "ROLLBACK_ACTIVATION" and phase["status"] == "PASS" for phase in phases)
        if not failures or not rollback_verified or not activation_verified or not phases or phases[-1]["phase"] != "CLEANUP" or phases[-1]["status"] != "PASS":
            raise ReceiptError("RECEIPT_STATE_INVALID", "RECOVERED requires preserved failure evidence and passing cleanup.")
    resume_digest = raw.get("resume_digest")
    needs_resume = status in {"RELEASE_B_REQUIRED", "RUN_INTERRUPTED_RECOVERABLE"}
    if needs_resume != (isinstance(resume_digest, str) and bool(DIGEST_RE.fullmatch(resume_digest))):
        raise ReceiptError("RECEIPT_STATE_INVALID", "resume_digest does not match the lifecycle state.")
    actions = raw.get("actions_not_performed")
    required_actions = {"publish", "report_send", "live_install_mutation"}
    if not isinstance(actions, list) or any(not isinstance(item, str) for item in actions) or not required_actions.issubset(actions):
        raise ReceiptError("RECEIPT_SCHEMA_INVALID", "actions_not_performed omits a required safety boundary.")
    limitations = raw.get("limitations")
    if not isinstance(limitations, list) or len(limitations) > 32 or any(not isinstance(item, str) for item in limitations):
        raise ReceiptError("RECEIPT_SCHEMA_INVALID", "limitations is invalid.")
    _require_text(raw.get("strongest_safe_claim"), "strongest_safe_claim")
    normalized = copy.deepcopy(raw)
    normalized["phases"] = phases
    return normalized


def _validate_prior_requests(prior_requests: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    if len(prior_requests) > MAX_CYCLES:
        raise ReceiptError("RECONCILIATION_LIMIT_EXCEEDED", "More than three prior cycles were supplied.")
    result: list[dict[str, object]] = []
    previous = None
    for index, item in enumerate(prior_requests, 1):
        if not isinstance(item, Mapping) or item.get("kind") != "VerificationFollowupRequest" or item.get("iteration") != index:
            raise ReceiptError("FOLLOWUP_REQUEST_INVALID", "Prior requests are not an ordered cycle chain.")
        verify_digest(item, "request_digest", "FOLLOWUP_REQUEST_INVALID")
        if item.get("previous_request_digest") != previous:
            raise ReceiptError("FOLLOWUP_REQUEST_INVALID", "Prior request digest chain is broken.")
        result.append(copy.deepcopy(dict(item)))
        previous = str(item["request_digest"])
    return result


def _finding_for(receipt: Mapping[str, object]) -> tuple[str, str, str]:
    status = str(receipt["status"])
    phases = receipt["phases"]
    assert isinstance(phases, list)
    if status == "RELEASE_B_REQUIRED":
        return ("RELEASE_B_EVIDENCE_REQUIRED", "UPDATE_DRY_RUN", "Resolve immutable Release B and prove the approved source branch points to it.")
    if status == "CLEANUP_REQUIRED":
        return ("CLEANUP_EVIDENCE_REQUIRED", "CLEANUP", "Obtain exact cleanup approval and provide the resulting cleanup phase receipt.")
    if status == "RUN_INTERRUPTED_RECOVERABLE":
        next_phase = PHASES[len(phases)] if len(phases) < len(PHASES) else "UNKNOWN"
        return ("RUN_RESUME_EVIDENCE_REQUIRED", next_phase, "Resume from the last verified boundary and provide a new aggregate receipt.")
    if status in {"RECOVERY_REQUIRED", "ROLLBACK_COMPLETE_CLEANUP_REQUIRED", "RECOVERED"}:
        failed = next(phase for phase in phases if phase.get("status") != "PASS")
        code = str(failed.get("error_code") or "PHASE_FAILED")
        recovery = " The disposable installation was restored." if status in {"ROLLBACK_COMPLETE_CLEANUP_REQUIRED", "RECOVERED"} else ""
        return (code, str(failed["phase"]), f"Repair {failed['phase']} and produce new executed evidence.{recovery}")
    return ("NONE", "NONE", "No follow-up evidence is required.")


def interpret_receipt(raw: object, *, prior_requests: Sequence[Mapping[str, object]] = ()) -> dict[str, object]:
    receipt = _validate_receipt(raw)
    prior = _validate_prior_requests(prior_requests)
    finding = _finding_for(receipt)
    finding_payload = {"code": finding[0], "phase": finding[1], "evidence_required": finding[2]}
    finding_signature = "sha256:" + hashlib.sha256(canonical_json(finding_payload)).hexdigest()
    status = str(receipt["status"])
    if status == "COMPLETE" and not receipt["limitations"]:
        interpretation_status = "CONSISTENT"
        check_status = "PASS"
        claim_status = "supported"
        strongest = "The declared lifecycle passed for the receipt's exact product, releases, adapter, target, and platform scope."
    else:
        failed = any(phase["status"] == "FAIL" for phase in receipt["phases"])
        interpretation_status = "INCONSISTENT" if failed else "EVIDENCE_GAP"
        check_status = "FAIL" if failed else "PARTIAL"
        claim_status = "contradicted" if failed else "partially_supported"
        strongest = str(receipt["strongest_safe_claim"])
    repeated = any(item.get("finding_signature") == finding_signature for item in prior)
    exhausted = len(prior) >= MAX_CYCLES
    if interpretation_status != "CONSISTENT" and (repeated or exhausted):
        interpretation_status = "RECONCILIATION_STALLED"
        check_status = "BLOCKED"
        claim_status = "partially_supported"
        strongest = "The same unresolved evidence boundary repeated or the three-cycle limit was reached; stop automatic follow-up."
    result: dict[str, object] = {
        "schema_version": 1,
        "kind": "LifecycleReceiptInterpretation",
        "protocol_version": PROTOCOL_VERSION,
        "source_receipt_digest": receipt["receipt_digest"],
        "run_id": receipt["run_id"],
        "status": interpretation_status,
        "check_status": check_status,
        "claim_status": claim_status,
        "evidence_method": "schema_validated",
        "strongest_safe_claim": strongest,
        "finding": finding_payload if interpretation_status != "CONSISTENT" else None,
        "finding_signature": finding_signature,
        "followup_required": interpretation_status in {"INCONSISTENT", "EVIDENCE_GAP"},
        "completed_cycles": len(prior),
        "max_cycles": MAX_CYCLES,
        "scope": {"product": receipt["product"], "adapter": receipt["adapter"], "target": receipt["target"]},
        "actions_not_performed": ["lifecycle_execution", "publish", "report_send", "live_install_mutation"],
    }
    result["interpretation_digest"] = object_digest(result, "interpretation_digest")
    return result


def build_followup_request(
    interpretation: Mapping[str, object],
    receipt: object,
    *,
    prior_requests: Sequence[Mapping[str, object]] = (),
) -> dict[str, object] | None:
    normalized = _validate_receipt(receipt)
    prior = _validate_prior_requests(prior_requests)
    verify_digest(interpretation, "interpretation_digest", "INTERPRETATION_INVALID")
    if interpretation.get("source_receipt_digest") != normalized["receipt_digest"]:
        raise ReceiptError("INTERPRETATION_INVALID", "Interpretation and receipt identities differ.")
    if not interpretation.get("followup_required"):
        return None
    if len(prior) >= MAX_CYCLES:
        return None
    signature = interpretation.get("finding_signature")
    if any(item.get("finding_signature") == signature for item in prior):
        return None
    finding = interpretation.get("finding")
    if not isinstance(finding, dict):
        raise ReceiptError("INTERPRETATION_INVALID", "Follow-up interpretation has no bounded finding.")
    value: dict[str, object] = {
        "schema_version": 1,
        "kind": "VerificationFollowupRequest",
        "protocol_version": PROTOCOL_VERSION,
        "source_receipt_digest": normalized["receipt_digest"],
        "interpretation_digest": interpretation["interpretation_digest"],
        "run_id": normalized["run_id"],
        "product": normalized["product"],
        "finding": copy.deepcopy(finding),
        "finding_signature": signature,
        "required_evidence": [finding["evidence_required"]],
        "allowed_action": "read_only_plan",
        "actions_not_authorized": ["execute", "publish", "report_send", "live_install_mutation", "cleanup"],
        "iteration": len(prior) + 1,
        "max_cycles": MAX_CYCLES,
        "previous_request_digest": prior[-1]["request_digest"] if prior else None,
    }
    value["request_digest"] = object_digest(value, "request_digest")
    return value


def _read_json(path: Path) -> dict[str, object]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            raise ReceiptError("INPUT_INVALID", "Input must be a bounded JSON file.")
        value = json.loads(path.read_text(encoding="utf-8"))
    except ReceiptError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReceiptError("INPUT_INVALID", f"Cannot read valid JSON from {path.name}.") from exc
    if not isinstance(value, dict):
        raise ReceiptError("INPUT_INVALID", f"{path.name} must contain a JSON object.")
    return value


def _error(exc: ReceiptError) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "FAIL",
        "code": exc.code,
        "problem": exc.message,
        "cause": "The supplied lifecycle evidence did not satisfy the read-only consumer contract.",
        "safe_state": "No lifecycle command, report, publication, or file mutation was performed.",
        "fix": exc.fix or "Regenerate or provide the exact untampered receipt and prior request chain.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("human", "json"), default="human")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("interpret", "followup"):
        command = subparsers.add_parser(name)
        command.add_argument("--receipt", type=Path, required=True)
        command.add_argument("--prior-request", type=Path, action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = _read_json(args.receipt)
        prior = [_read_json(path) for path in args.prior_request]
        interpretation = interpret_receipt(receipt, prior_requests=prior)
        value = interpretation if args.command == "interpret" else build_followup_request(interpretation, receipt, prior_requests=prior)
        if value is None:
            value = {"schema_version": 1, "status": "NO_FOLLOWUP", "reason": interpretation["status"]}
        if args.format == "json":
            print(json.dumps(value, sort_keys=True, ensure_ascii=False))
        else:
            print(f"LIFECYCLE RECEIPT: {value.get('status', value.get('kind'))}")
            print(f"strongest_safe_claim: {value.get('strongest_safe_claim', 'No follow-up request was produced.')}")
            for field in ("check_status", "claim_status", "source_receipt_digest", "interpretation_digest", "request_digest"):
                if value.get(field) is not None:
                    print(f"{field}: {value[field]}")
        return 0
    except ReceiptError as exc:
        value = _error(exc)
        output = json.dumps(value, sort_keys=True, ensure_ascii=False) if args.format == "json" else f"LIFECYCLE RECEIPT: FAIL\ncode: {exc.code}\nproblem: {exc.message}\nfix: {value['fix']}"
        print(output, file=sys.stderr)
        return 2
    except Exception:
        value = _error(ReceiptError("INTERNAL_ERROR", "The receipt consumer hit an unexpected internal error."))
        output = json.dumps(value, sort_keys=True, ensure_ascii=False) if args.format == "json" else "LIFECYCLE RECEIPT: FAIL\ncode: INTERNAL_ERROR\nproblem: Unexpected internal error."
        print(output, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

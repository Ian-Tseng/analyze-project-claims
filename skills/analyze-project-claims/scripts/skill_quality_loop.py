#!/usr/bin/env python3
"""CLI for bounded cross-skill receipts and local-only quality proposals."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from _internal.skill_quality import contract
from _internal.skill_quality import contribution
from _internal.skill_quality.store import QualityStore


ANALYZER_VERSION = "1.0.0"
MAX_HOOK_EVENT_BYTES = contract.MAX_ASSISTANT_MESSAGE_BYTES + 8192


def default_state_directory() -> Path:
    plugin_data = os.environ.get("PLUGIN_DATA")
    if plugin_data:
        return Path(plugin_data) / "skill-quality"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "analyze-project-claims" / "skill-quality"
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "analyze-project-claims" / "skill-quality"
    return Path.home() / ".local" / "state" / "analyze-project-claims" / "skill-quality"


def _read_marker(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "marker", None):
        return contract.parse_marker(args.marker)
    if getattr(args, "receipt", None):
        value = json.loads(args.receipt.read_text(encoding="utf-8"))
        return contract.validate_receipt(value)
    raise contract.QualityError("NO_COMPATIBLE_RECEIPT", "Provide --marker or --receipt.")


def _error(exc: contract.QualityError) -> dict[str, Any]:
    fixes = {
        "NO_COMPATIBLE_RECEIPT": "Run a compatible producer, then retry with its exact trailing marker.",
        "RECEIPT_SCHEMA_VIOLATION": "Update the producer and run receipt validate locally.",
        "RECEIPT_EXPIRED": "Generate a new receipt; expired receipts are never replayed.",
        "RECEIPT_FUTURE_DATED": "Correct the producer clock and generate a new receipt.",
        "RECEIPT_BUSY": "Retry after the local lease expires.",
        "CONTRIBUTION_OUTCOME_UNKNOWN": "Search GitHub for the exact contribution ID before any retry.",
        "UPDATE_AUTHORITY_CONFLICT": "Keep exactly one update authority for this installation.",
    }
    uncertain_outbound = exc.code == "CONTRIBUTION_OUTCOME_UNKNOWN"
    contribution_network_possible = exc.code.startswith("CONTRIBUTION_") or exc.code == "PUBLIC_ISSUE_APPROVAL_REQUIRED"
    return {
        "status": "ERROR",
        "code": exc.code,
        "problem": exc.message,
        "cause": exc.code,
        "effect": (
            "A GitHub issue may have been created; do not retry until the contribution ID is reconciled."
            if uncertain_outbound
            else "No quality proposal or outbound action was completed."
        ),
        "fix": fixes.get(exc.code, "Inspect quality-loop doctor output and retry after correcting local state."),
        "retry": not uncertain_outbound,
        "safety": (
            "No transcript or project file was inspected; GitHub may have been queried by the contribution command."
            if contribution_network_possible
            else "No transcript, project file, or network endpoint was inspected."
        ),
        "docs": "docs/SKILL_QUALITY_LOOP.md#error-contracts",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage bounded SkillOutcomeReceipts and local proposals.")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--state-dir", type=Path, default=default_state_directory())
    subparsers = parser.add_subparsers(dest="command", required=True)

    emit = subparsers.add_parser("emit", help="Create a content-free producer receipt marker.")
    emit.add_argument("--owner", default="Ian-Tseng")
    emit.add_argument("--repository", required=True)
    emit.add_argument("--skill", required=True)
    emit.add_argument("--version", required=True)
    emit.add_argument("--package-digest", required=True)
    emit.add_argument("--outcome", choices=sorted(contract.OUTCOMES), required=True)
    emit.add_argument("--quality-signal", choices=sorted(contract.QUALITY_SIGNALS), required=True)
    emit.add_argument("--requested-action", choices=sorted(contract.REQUESTED_ACTIONS))
    emit.add_argument("--ttl-seconds", type=int, default=3600)
    emit.add_argument("--causal-depth", type=int, choices=(0, 1), default=0)
    emit.add_argument("--prior-digest")

    validate = subparsers.add_parser("validate", help="Validate one receipt without storing it.")
    validate.add_argument("--marker")
    validate.add_argument("--receipt", type=Path)

    consume = subparsers.add_parser("consume", help="Commit one idempotent local proposal.")
    consume.add_argument("--marker")
    consume.add_argument("--receipt", type=Path)

    subparsers.add_parser("status", help="Show local quality-loop counts.")
    subparsers.add_parser("doctor", help="Diagnose adapter and update-authority topology.")
    subparsers.add_parser("conformance", help="Run the offline receipt-to-proposal fixture.")
    subparsers.add_parser("hook-stop", help=argparse.SUPPRESS)

    show = subparsers.add_parser("proposal-show", help="Show one local proposal.")
    show.add_argument("--proposal-id", required=True)
    dismiss = subparsers.add_parser("proposal-dismiss", help="Dismiss one local proposal.")
    dismiss.add_argument("--proposal-id", required=True)
    preview = subparsers.add_parser("contribution-preview", help="Prepare an enum-only owner contribution.")
    preview.add_argument("--proposal-id", required=True)
    submit = subparsers.add_parser("contribution-submit", help="Submit one exactly approved contribution.")
    submit.add_argument("--draft", type=Path, required=True)
    submit.add_argument("--approve", required=True)
    submit.add_argument("--approved", action="store_true")
    submit.add_argument("--allow-public-issue", action="store_true")
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    store = QualityStore(args.state_dir)
    if args.command == "emit":
        if not 1 <= args.ttl_seconds <= 86400:
            raise contract.QualityError("RECEIPT_SCHEMA_VIOLATION", "ttl-seconds must be between 1 and 86400.")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        receipt = contract.create_receipt(
            owner=args.owner,
            repository=args.repository,
            skill=args.skill,
            version=args.version,
            package_digest_sha256=args.package_digest,
            outcome=args.outcome,
            quality_signal=args.quality_signal,
            requested_action=args.requested_action
            or ("none" if args.quality_signal == "no_issue" else "analyze_quality"),
            created_at=now,
            expires_at=now + timedelta(seconds=args.ttl_seconds),
            causal_depth=args.causal_depth,
            prior_receipt_digest_sha256=args.prior_digest,
        )
        return {"status": "RECEIPT_READY", "receipt": receipt, "marker": contract.format_marker(receipt)}
    if args.command == "validate":
        receipt = _read_marker(args)
        return {"status": "RECEIPT_VALID", "receipt_digest_sha256": receipt["receipt_digest_sha256"]}
    if args.command == "consume":
        proposal = store.consume(_read_marker(args), analyzer_version=ANALYZER_VERSION) if (args.marker or args.receipt) else store.consume_next(analyzer_version=ANALYZER_VERSION)
        proposal = dict(proposal)
        proposal_status = proposal.pop("status")
        if proposal_status == "no_action":
            return {"status": "NO_QUALITY_FOLLOWUP", **proposal}
        return {"status": "QUALITY_PROPOSAL_READY", "proposal_status": proposal_status, **proposal}
    if args.command == "status":
        return store.status()
    if args.command == "doctor":
        plugin_managed = bool(os.environ.get("PLUGIN_ROOT"))
        return {
            "status": "READY",
            "automatic_adapter": "codex-plugin-stop" if plugin_managed else "UNAVAILABLE",
            "portable_handoff": "AVAILABLE",
            "update_authority": "plugin-manager" if plugin_managed else "github-cli-or-manual",
            "automatic_claim": "at-most-one-continuation-request",
            "durable_claim": "one-idempotent-local-proposal-per-receipt-and-analyzer-version",
            "outbound": "NONE",
        }
    if args.command == "proposal-show":
        return {"status": "READY", "proposal": store.proposal(args.proposal_id)}
    if args.command == "proposal-dismiss":
        return {"status": "DISMISSED", "proposal": store.dismiss(args.proposal_id)}
    if args.command == "contribution-preview":
        return contribution.prepare_contribution(store.proposal(args.proposal_id), args.state_dir)
    if args.command == "contribution-submit":
        result = contribution.submit_contribution(
            args.draft,
            approve=args.approve,
            approved=args.approved,
            allow_public_issue=args.allow_public_issue,
        )
        try:
            store.record_outbound(result["contribution_id"], result["issue_url"])
        except (contract.QualityError, OSError, TypeError, ValueError):
            result = {
                **result,
                "local_accounting": "WARNING",
                "warning": (
                    "The GitHub issue is confirmed and the one-use submission record is durable, "
                    "but secondary local outbound accounting failed. Do not resubmit."
                ),
            }
        return result
    if args.command == "hook-stop":
        raw_event = sys.stdin.buffer.read(MAX_HOOK_EVENT_BYTES + 1)
        if len(raw_event) > MAX_HOOK_EVENT_BYTES:
            return {}
        try:
            event = json.loads(raw_event.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return {}
        return store.handle_stop_event(event)
    if args.command == "conformance":
        now = datetime.now(timezone.utc).replace(microsecond=0)
        receipt = contract.create_receipt(
            owner="Ian-Tseng",
            repository="quality-loop-fixture",
            skill="quality-loop-fixture",
            version="1.0.0",
            package_digest_sha256="0" * 64,
            outcome="completed_with_limitations",
            quality_signal="claim_evidence_gap",
            requested_action="analyze_quality",
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        marker = contract.format_marker(receipt)
        parsed = contract.extract_trailing_marker("fixture complete\n" + marker)
        first = store.consume(parsed, analyzer_version=ANALYZER_VERSION)
        second = store.consume(parsed, analyzer_version=ANALYZER_VERSION)
        return {
            "status": "QUALITY_PROPOSAL_READY",
            "receipt_digest_sha256": receipt["receipt_digest_sha256"],
            "proposal_id": first["proposal_id"],
            "replay_deduplicated": second["deduplicated"],
            "outbound": "NONE",
        }
    raise contract.QualityError("QUALITY_COMMAND_INVALID", "Unknown quality-loop command.")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = _run(args)
        code = 0
    except (contract.QualityError, contribution.ContributionError, OSError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, contract.QualityError):
            error = exc
        elif isinstance(exc, contribution.ContributionError):
            error = contract.QualityError(exc.code, exc.message)
        else:
            error = contract.QualityError("QUALITY_COMMAND_FAILED", str(exc))
        output = _error(error)
        code = 2
    if args.command == "hook-stop":
        print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    elif args.format == "json":
        print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    else:
        print(output.get("status", "ERROR"))
        print(json.dumps(output, ensure_ascii=True, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

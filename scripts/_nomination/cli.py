"""Developer CLI: preflight, nominate, show and verify; no acceptance actions."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .common import Failure, MAX_JSON_BYTES, canonical, fail, sha
from .engine import Context, read_bundle, read_request, verify
from .compiler import compile_review, handoff, native_command, sidecar
from .filesystem import absolute, atomic_create, entry_stat, linked, make_directories, safe_read

DOC = "docs/EVIDENCE_NOMINATION_DEVELOPMENT.md"


class Parser(argparse.ArgumentParser):
    def error(self, message):
        fail(2, "invalid_input", "arguments")


def parser():
    p = Parser(description="Development-only local evidence nominations; no acceptance or append.")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("preflight", "nominate", "show", "verify", "compile", "handoff"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--format", choices=("human", "json"), default="human")
        if name in ("preflight", "nominate"):
            cmd.add_argument("--request", required=True, type=Path)
        else:
            cmd.add_argument("--bundle", required=True, type=Path)
        if name != "show":
            cmd.add_argument("--project-root", required=True, type=Path)
            cmd.add_argument("--map-root", required=True, type=Path)
            cmd.add_argument("--record", type=Path)
        if name in ("compile", "handoff"):
            cmd.add_argument("--selection", required=True, type=Path)
            cmd.add_argument("--output", required=True, type=Path)
        if name == "handoff":
            cmd.add_argument("--candidate", required=True, type=Path)
        if name == "nominate":
            cmd.add_argument("--out-dir", required=True, type=Path)
    return p


def receipt(code, *, value=None, path=None, raw=None, changed=False):
    target = None if value is None else value.get("target", value.get("request", {}).get("target"))
    return {"schema_version": "1.0", "status": "ok", "code": code,
            "effect": "artifacts_created" if changed else "read_only", "changed": changed, "retryable": False,
            "artifact_path": str(absolute(path)) if path else None, "artifact_sha256": sha(raw) if raw is not None else None,
            "target": target, "nomination_count": len(value.get("nominations", [])) if value else 0,
            "completeness": value.get("completeness") if value else None,
            "exclusions": value.get("exclusions", []) if value else [], "truncations": value.get("truncations", []) if value else [],
            "network": False, "accepted_state_changed": False, "next_command": None, "documentation": DOC}


def publish(ctx, bundle):
    raw = canonical(bundle) + b"\n"
    out = ctx.output
    path = out / (bundle["bundle_id"] + ".bundle.json")
    selection_path = out / (bundle["bundle_id"] + ".selection.json")
    selection = {"schema_version": "1.0", "artifact_kind": "nomination_selection",
                 "bundle": {"bundle_id": bundle["bundle_id"], "canonical_payload_sha256": bundle["canonical_payload_sha256"], "file_sha256": sha(raw)},
                 "reviewer_label": "unreviewed", "selections": [], "reviewer_input": None}
    ctx.schemas.validate(selection, "selection")
    desired = ((path, raw), (selection_path, canonical(selection) + b"\n"))
    changed = False
    created = []
    try:
        # Creation begins only after the complete read-only scan and deadline check.
        directories = make_directories(out)
        changed = bool(directories)
        created.extend(directories)
        pending = []
        for target, data in desired:
            info = entry_stat(target, missing_ok=True)
            if info is None:
                pending.append((target, data))
            elif linked(info):
                fail(2, "safety_refusal", "output_link")
            elif safe_read(target, MAX_JSON_BYTES) != data:
                fail(5, "recovery_required", "existing_different_bytes")
        for target, data in pending:
            try:
                atomic_create(target, data)
                changed = True
                created.append(str(target))
            except (OSError, Failure) as publication_error:
                if isinstance(publication_error, Failure) and publication_error.changed:
                    raise
                # A competing writer may have won. Reuse only the exact bytes.
                try:
                    if safe_read(target, MAX_JSON_BYTES) == data:
                        continue
                except (OSError, Failure):
                    pass
                fail(5, "atomic_write_failure", "exclusive_publication")
    except Failure as exc:
        raise Failure(5 if exc.exit_code == 3 else exc.exit_code,
                      "atomic_write_failure" if exc.exit_code == 3 else exc.code,
                      exc.reason, changed=changed or exc.changed, artifacts=created + exc.artifacts) from None
    except OSError:
        raise Failure(5, "atomic_write_failure", "publication_io", changed=changed, artifacts=created) from None
    code = "reused_identical" if not pending else "partial" if bundle["completeness"] == "partial" else "zero_nominations" if not bundle["nominations"] else "complete"
    result = receipt(code, value=bundle, path=path, raw=raw, changed=changed)
    result["selection_path"] = str(selection_path)
    result["next_command"] = ["show", "--bundle", str(path)]
    return result



def publish_sidecar(path, value):
    raw = canonical(value) + b"\n"
    if len(raw) > MAX_JSON_BYTES:
        fail(2, "invalid_input", "artifact_size")
    info = entry_stat(path, missing_ok=True)
    if info is not None:
        if safe_read(path, MAX_JSON_BYTES) == raw:
            return raw, False
        fail(5, "recovery_required", "existing_different_bytes")
    try:
        atomic_create(path, raw)
    except (OSError, Failure) as exc:
        if isinstance(exc, Failure) and exc.changed:
            raise
        try:
            if safe_read(path, MAX_JSON_BYTES) == raw:
                return raw, False
        except (OSError, Failure):
            pass
        fail(5, "atomic_write_failure", "exclusive_publication")
    return raw, True


def compile_or_handoff(args):
    protected = [args.selection]
    if args.command == "handoff":
        protected.append(args.candidate)
    output = sidecar(args.output, args.bundle, protected)
    if args.command == "compile":
        candidate, bundle = compile_review(args.bundle, args.selection, args.project_root, args.map_root, args.record)
        raw, changed = publish_sidecar(output, candidate)
        next_command = ["handoff", "--candidate", str(output), "--bundle", str(absolute(args.bundle)),
                        "--selection", str(absolute(args.selection)), "--project-root", str(absolute(args.project_root)),
                        "--map-root", str(absolute(args.map_root)), "--output", str(output.with_name(output.name + ".payload.json"))]
        if args.record:
            next_command += ["--record", str(absolute(args.record))]
        code = "compiled"
    else:
        candidate, bundle = handoff(args.candidate, args.bundle, args.selection, args.project_root, args.map_root, args.record)
        raw, changed = publish_sidecar(output, candidate["payload"])
        next_command = native_command(candidate, output, args.project_root, args.map_root)
        code = "handoff_prepared"
    result = receipt(code if changed else "reused_identical", value=bundle, path=output, raw=raw, changed=changed)
    result.update(next_command=next_command, selected_count=len(candidate["provenance"]["selected_nomination_ids"]),
                  candidate_id=candidate["candidate_id"], verification="current_local_replay_and_review_binding")
    return result


def run(args):
    if args.command in ("compile", "handoff"):
        return compile_or_handoff(args)
    if args.command in ("preflight", "nominate"):
        request = read_request(args.request)
        ctx = Context(request, args.project_root, args.map_root, request_path=args.request,
                      record_path=args.record, output=getattr(args, "out_dir", None))
        if args.command == "preflight":
            return receipt("ready", value=ctx.request)
        return publish(ctx, ctx.build())
    if args.command == "show":
        raw, value = read_bundle(args.bundle)
        result = receipt("inspected", value=value, path=args.bundle, raw=raw)
        result["nominations"] = value["nominations"]
        result["verification"] = "self_integrity_only"
        return result
    raw, value = verify(args.bundle, args.project_root, args.map_root, args.record)
    result = receipt("verified", value=value, path=args.bundle, raw=raw)
    result["verification"] = "current_local_replay"
    return result


def error_receipt(exc):
    result = receipt(exc.code, changed=exc.changed)
    result.update(status="error", retryable=exc.exit_code == 3,
                  effect="partial_artifacts_may_exist" if exc.changed else "no_artifact_created",
                  reason=exc.reason, created_artifacts=exc.artifacts,
                  problem="The requested operation could not complete.",
                  cause=exc.reason,
                  fix="Review the input and local files; use a clean output location for conflicting artifacts.",
                  retry="Rerun the same command after correcting the cause; rerun nomination for stale evidence.")
    return result


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_output = any(argv[i:i+2] == ["--format", "json"] for i in range(len(argv)))
    code = 0
    try:
        args = parser().parse_args(argv)
        json_output = args.format == "json"
        result = run(args)
    except Failure as exc:
        code = exc.exit_code
        result = error_receipt(exc)
    except OSError:
        code = 3
        result = error_receipt(Failure(3, "local_io_retry", "filesystem"))
    if code:
        print(f"{result['code']}: {result['reason']}. No acceptance or append was performed.", file=sys.stderr)
    if json_output:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"{result['code']}: {result['nomination_count']} nominations; {result['completeness'] or result['status']}.")
        if result["artifact_path"]:
            print(result["artifact_path"])
        if result.get("next_command"):
            print("Next command arguments (not executed): " + json.dumps(result["next_command"], ensure_ascii=False))
        if code:
            for key in ("problem", "cause", "effect", "fix", "retry"):
                print(f"{key.title()}: {result[key]}")
        for n in result.get("nominations", []):
            print(f"\n{n['path']}:{n['line_start']}-{n['line_end']} (score {n['score']})\n{n['excerpt']}")
        if result.get("verification") == "self_integrity_only":
            print("Source freshness has not been checked; use verify for local replay.")
    return code

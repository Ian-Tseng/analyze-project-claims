"""Read-only nomination engine, authoritative preflight, and bundle replay."""
from __future__ import annotations

import copy
import heapq
import json
import os
import stat
import sys
import unicodedata
from collections import Counter
from pathlib import Path

from .common import (CONTRACT, ROOT, SCHEMA_NAMES, SKILL, MAX_JSON_BYTES, Deadline,
                     Failure, Schemas, canonical, digest, fail, inspect_json,
                     normalize_request, parse_json, relative_path, safe_text, secret, sha)
from .filesystem import absolute, directory, entry_stat, linked, list_names, safe_read

# These are explicitly trusted sibling package modules, never project modules.
TRUSTED_SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(TRUSTED_SCRIPTS))
from reconcile_component_map import MapError, _validate_map
from _internal.evidence_bound_scan import AuditRecordError, _verify_record_integrity
from _internal.component_evidence.identity import EngineIdentityError, verified_engine_summary

TRAVERSAL_ENTRIES = 25000
TRAVERSAL_DEPTH = 64
SKIP_NAMES = {".git", ".hg", ".svn"}
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".whl"}
ARCHIVE_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"7z\xbc\xaf\x27\x1c", b"Rar!", b"BZh", b"\xfd7zXZ\x00")


def code_files():
    # Closed trusted implementation list; adding a helper requires updating this list.
    names = ["scripts/evidence_nomination.py", "scripts/_nomination/__init__.py",
             "scripts/_nomination/common.py", "scripts/_nomination/filesystem.py",
             "scripts/_nomination/engine.py", "scripts/_nomination/cli.py",
             "contracts/evidence-nomination/v1/policy.json"]
    prefix = "skills/analyze-project-claims/"
    names += [prefix + n for n in (
        "scripts/reconcile_component_map.py", "scripts/_internal/__init__.py",
        "scripts/_internal/evidence_bound_scan.py", "scripts/_internal/component_evidence/__init__.py",
        "scripts/_internal/component_evidence/identity.py", "references/scan-record-v2.schema.json",
        "references/scan-record-output-v2.schema.json", "references/component-map-observation.schema.json")]
    return sorted(names)


def finder_identity(deadline):
    files = [{"path": n, "sha256": sha(safe_read(ROOT / n, MAX_JSON_BYTES, deadline))} for n in code_files()]
    return {"finder_id": "literal-line-v1", "implementation_kind": "runtime",
            "code_sha256": digest(files), "contract_sha256": sha(safe_read(CONTRACT / "CONTRACT.md", MAX_JSON_BYTES, deadline)),
            "unicode_version": unicodedata.unidata_version,
            "schemas": [{"path": name + ".schema.json", "sha256": sha(safe_read(CONTRACT / (name + ".schema.json"), MAX_JSON_BYTES, deadline))} for name in SCHEMA_NAMES]}


def inside(child, parent):
    return child == parent or child.is_relative_to(parent)


def installed_path(path):
    parts = tuple(x.casefold() for x in path.parts)
    return any(parts[i] in {".codex", ".agents", ".claude"} and parts[i + 1] in {"skills", "plugins"} for i in range(len(parts) - 1)) or inside(path, SKILL)


def validate_output(path, project, roots, map_root):
    path = absolute(path)
    if not path.is_relative_to(project) or path == project or installed_path(path):
        fail(2, "safety_refusal", "output_scope")
    relative_path(path.relative_to(project).as_posix())
    if inside(path, project / "validation") or inside(path, map_root) or any(inside(root, path) for root in roots):
        fail(2, "safety_refusal", "output_scope")
    cursor = project
    missing = False
    for part in path.relative_to(project).parts:
        cursor /= part
        if not missing:
            info = entry_stat(cursor, missing_ok=True)
            if info is None:
                missing = True
            elif linked(info) or not stat.S_ISDIR(info.st_mode):
                fail(2, "safety_refusal", "output_directory")
    return path


class Context:
    def __init__(self, request, project, map_root, *, request_path=None, record_path=None, output=None):
        self.schemas = Schemas()
        self.request = normalize_request(request, self.schemas)
        self.deadline = Deadline(self.request["resource_policy"]["timeout_seconds"])
        self.project = directory(project)
        self.map_root = directory(map_root)
        if not self.map_root.is_relative_to(self.project):
            fail(2, "safety_refusal", "map_scope")
        self.map_path = self.map_root / "accepted-map.json"
        self.record_path = absolute(record_path) if record_path else None
        self.roots = []
        for root in self.request["allowed_roots"]:
            path = self.project if root == "." else self.project / root
            if installed_path(path) or inside(path, self.map_root) or any(p in SKIP_NAMES for p in path.relative_to(self.project).parts):
                fail(2, "safety_refusal", "root_scope")
            self.roots.append(directory(path))
        self.excluded = {self.map_root, self.project / ".analyze-project-claims/nominations"}
        # Equivalent request JSON is recognized by its normalized contents during
        # scanning, so verify needs no machine-specific original request path.
        if self.record_path:
            self.excluded.add(self.record_path)
        self.output = validate_output(output, self.project, self.roots, self.map_root) if output else None
        if self.output:
            self.excluded.add(self.output)
        self.finder = finder_identity(self.deadline)
        self.check_authority()

    def check_authority(self):
        raw = safe_read(self.map_path, MAX_JSON_BYTES, self.deadline)
        value = parse_json(raw)
        try:
            _validate_map(value, "nomination-map")
            engine = verified_engine_summary(SKILL)
        except (MapError, EngineIdentityError):
            fail(4, "stale_identity", "map_authority")
        expected = self.request["map"]
        current = {"map_id": value["map_id"], "canonical_payload_sha256": value["integrity"]["canonical_payload_sha256"], "file_sha256": sha(raw)}
        if current != expected or value["map_state"] != "accepted" or value["skill_sha256"] != sha(safe_read(SKILL / "SKILL.md", MAX_JSON_BYTES, self.deadline)):
            fail(4, "stale_identity", "map_identity_mismatch")
        target = self.request["target"]
        ref = target["element_ref"]
        elements = {(c["component_id"], e["element_id"]) for c in value["components"] for e in c["elements"]}
        if (ref["component_id"], ref["element_id"]) not in elements:
            fail(2, "invalid_input", "unknown_element")
        if target["kind"] == "claim":
            if self.record_path is None:
                fail(2, "invalid_input", "record_required")
            raw_record = safe_read(self.record_path, MAX_JSON_BYTES, self.deadline)
            if sha(raw_record) != target["record_sha256"]:
                fail(4, "stale_identity", "record_identity_mismatch")
            record = parse_json(raw_record)
            try:
                _verify_record_integrity(record)
            except AuditRecordError:
                fail(4, "tampered_identity", "record_authority")
            scan = record["scan"]
            integrity = record["integrity"]
            claims = [c for c in record["claims"] if c["claim_id"] == target["claim_id"]]
            source_code = sha(safe_read(TRUSTED_SCRIPTS / "_internal/evidence_bound_scan.py", MAX_JSON_BYTES, self.deadline))
            output_schema = sha(safe_read(SKILL / "references/scan-record-output-v2.schema.json", MAX_JSON_BYTES, self.deadline))
            if (scan["scan_id"] != target["scan_id"] or scan["accepted_map"]["sha256"] != current["file_sha256"] or scan["accepted_map"]["map_id"] != current["map_id"]
                or scan["skill_sha256"] != value["skill_sha256"] or scan["engine_identity"] != engine
                or integrity["recorder_sha256"] != source_code or integrity["renderer_sha256"] != source_code or integrity["output_schema_sha256"] != output_schema
                or len(claims) != 1 or claims[0]["claim_digest"] != target["claim_digest"] or claims[0]["element_ref"] != ref):
                fail(4, "stale_identity", "record_identity_mismatch")
        elif self.record_path is not None:
            fail(2, "invalid_input", "unexpected_record")
        self.deadline.check()

    def skip(self, path):
        relative = path.relative_to(self.project)
        return any(p in SKIP_NAMES for p in relative.parts) or installed_path(path) or any(inside(path, x) for x in self.excluded)

    def entries(self, exclusions):
        heap = []
        seen = set()
        for path in self.roots:
            rel = path.relative_to(self.project).as_posix()
            heapq.heappush(heap, ("" if rel == "." else rel + "/", path, True))
        visited = 0
        while heap:
            self.deadline.check()
            _, path, is_dir = heapq.heappop(heap)
            if self.skip(path):
                continue
            if not is_dir:
                yield path
                continue
            rel = path.relative_to(self.project)
            if len(rel.parts) > TRAVERSAL_DEPTH:
                fail(2, "safety_refusal", "traversal_depth")
            names = list_names(path, TRAVERSAL_ENTRIES - visited, self.deadline)
            visited += len(names)
            for name in names:
                child = path / name
                if self.skip(child):
                    continue
                relname = child.relative_to(self.project).as_posix()
                try:
                    relative_path(relname)
                except Failure:
                    exclusions["path_policy"] += 1
                    continue
                casekey = relname.casefold()
                if casekey in seen:
                    fail(2, "safety_refusal", "path_case_collision")
                seen.add(casekey)
                info = entry_stat(child)
                if linked(info):
                    exclusions["link_or_reparse"] += 1
                    continue
                if stat.S_ISDIR(info.st_mode):
                    heapq.heappush(heap, (relname + "/", child, True))
                elif stat.S_ISREG(info.st_mode):
                    heapq.heappush(heap, (relname, child, False))
                else:
                    exclusions["path_policy"] += 1

    def build(self):
        policy = self.request["resource_policy"]
        queries = sorted([{"query_id": "query-" + digest(r), "requirement": r} for r in self.request["requirements"]], key=lambda q: q["query_id"])
        exclusions = Counter()
        truncations = {}
        corpus = []
        hits = []
        attempted = total = raw_matches = 0
        stop_matches = False
        def truncate(name, observed):
            truncations[name] = {"budget": name, "limit": policy[name], "observed": observed}
        for path in self.entries(exclusions):
            self.deadline.check()
            info = entry_stat(path)
            if linked(info) or not stat.S_ISREG(info.st_mode):
                fail(3, "local_io_retry", "unstable_read")
            attempted += 1
            if attempted > policy["max_files"]:
                truncate("max_files", attempted)
                break
            if total + info.st_size > policy["max_total_bytes"]:
                truncate("max_total_bytes", total + info.st_size)
                break
            total += info.st_size
            suffix_archive = path.suffix.lower() in ARCHIVE_SUFFIXES
            if info.st_size > policy["max_file_bytes"]:
                exclusions["archive" if suffix_archive else "oversize"] += 1
                continue
            raw = safe_read(path, policy["max_file_bytes"], self.deadline)
            if len(raw) != info.st_size:
                fail(3, "local_io_retry", "unstable_read")
            reason = None
            if suffix_archive or raw.startswith(ARCHIVE_MAGIC) or raw[257:262] == b"ustar":
                reason = "archive"
            elif raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw:
                reason = "binary_or_encoding"
            else:
                try:
                    text = raw.decode("utf-8")
                except UnicodeError:
                    reason = "binary_or_encoding"
                else:
                    if text.startswith("version https://git-lfs.github.com/spec/v1"):
                        reason = "lfs_pointer"
                    elif not safe_text(text, multiline=True):
                        reason = "unsafe_unicode"
                    elif secret(text):
                        reason = "secret"
                    elif not raw:
                        reason = "empty_file"
            if reason:
                exclusions[reason] += 1
                continue
            # Input-request copies are sidecars, never evidence. Recognize them
            # identically in nominate and verify, including differently formatted JSON.
            if text.lstrip().startswith("{"):
                try:
                    candidate_request = parse_json(raw)
                    if candidate_request.get("artifact_kind") == "gap_request" and normalize_request(candidate_request, self.schemas) == self.request:
                        continue
                except (Failure, AttributeError):
                    pass
            rel = path.relative_to(self.project).as_posix()
            source_sha = sha(raw)
            corpus.append({"path": rel, "sha256": source_sha, "size_bytes": len(raw)})
            offset = 0
            # splitlines recognizes more than LF; use explicit LF to preserve the contract.
            lines = raw.split(b"\n")
            for index, content in enumerate(lines):
                self.deadline.check()
                if index == len(lines) - 1 and not content:
                    break
                selected = content + (b"\n" if index < len(lines) - 1 else b"")
                line = selected.decode("utf-8")
                matches = []
                for query in queries:
                    r = query["requirement"]
                    if not all(t in line for t in r["all_terms"]) or (r["any_terms"] and not any(t in line for t in r["any_terms"])) or any(t in line for t in r["exclude_terms"]):
                        continue
                    raw_matches += 1
                    if raw_matches > policy["max_raw_matches"]:
                        truncate("max_raw_matches", raw_matches)
                        stop_matches = True
                        break
                    if len(selected) > policy["max_range_bytes"]:
                        truncate("max_range_bytes", max(len(selected), truncations.get("max_range_bytes", {}).get("observed", 0)))
                        continue
                    matches.append({"query_id": query["query_id"], "requirement_id": r["requirement_id"], "requested_role": r["requested_role"], "score": 100*len(r["all_terms"]) + 10*sum(t in line for t in r["any_terms"])})
                if matches:
                    score = max(m["score"] for m in matches)
                    excerpt = selected[:policy["max_excerpt_bytes"]].decode("utf-8", errors="ignore")
                    hit = {"path": rel, "source_sha256": source_sha, "byte_start": offset, "byte_end": offset + len(selected), "line_start": index + 1, "line_end": index + 1,
                           "range_sha256": sha(selected), "excerpt": excerpt, "excerpt_truncated": len(excerpt.encode("utf-8")) < len(selected), "score": score,
                           "query_id": min(m["query_id"] for m in matches if m["score"] == score), "matches": matches}
                    hits.append({"nomination_id": "hit-" + digest(hit), **hit})
                offset += len(selected)
                if stop_matches:
                    break
            if stop_matches:
                break
        hits.sort(key=lambda h: (-h["score"], h["path"], h["byte_start"], h["byte_end"], h["query_id"]))
        selected_hits = []
        counts = Counter()
        pre_counts = Counter(m["requirement_id"] for h in hits for m in h["matches"])
        for hit in hits:
            ids = [m["requirement_id"] for m in hit["matches"]]
            if len(selected_hits) >= policy["max_nominations"]:
                truncate("max_nominations", len(hits))
                continue
            if any(counts[r] >= policy["max_per_requirement"] for r in ids):
                truncate("max_per_requirement", max(pre_counts.values()))
                continue
            selected_hits.append(hit)
            counts.update(ids)
        # Recheck all admitted source bytes and authority before writing any artifact.
        for source in corpus:
            if sha(safe_read(self.project / source["path"], policy["max_file_bytes"], self.deadline)) != source["sha256"]:
                fail(3, "local_io_retry", "unstable_read")
        self.check_authority()
        if finder_identity(self.deadline) != self.finder:
            fail(4, "stale_identity", "finder_identity")
        reason_order = json.loads((CONTRACT / "policy.json").read_bytes())["exclusion_codes"]
        payload = {"schema_version": "1.0", "artifact_kind": "nomination_bundle", "request": self.request,
                   "finder": self.finder, "corpus": corpus, "queries": queries, "nominations": selected_hits,
                   "exclusions": [{"reason": r, "count": exclusions[r]} for r in reason_order if exclusions[r]],
                   "truncations": [truncations[k] for k in sorted(truncations)], "completeness": "partial" if truncations else "complete"}
        bundle = {**payload, "bundle_id": "nomination-" + digest(payload), "canonical_payload_sha256": digest(payload)}
        self.schemas.validate(bundle, "bundle")
        self.deadline.check()
        return bundle


def read_request(path):
    return parse_json(safe_read(path, MAX_JSON_BYTES))


def read_bundle(path):
    raw = safe_read(path, MAX_JSON_BYTES)
    value = parse_json(raw)
    schemas = Schemas()
    schemas.validate(value, "bundle")
    payload = {k: v for k, v in value.items() if k not in ("bundle_id", "canonical_payload_sha256")}
    if value["canonical_payload_sha256"] != digest(payload) or value["bundle_id"] != "nomination-" + digest(payload):
        fail(4, "tampered_identity", "bundle_identity_mismatch")
    if normalize_request(value["request"], schemas) != value["request"]:
        fail(4, "tampered_identity", "noncanonical_request")
    corpus = {}
    for source in value["corpus"]:
        relative_path(source["path"])
        if source["path"].casefold() in corpus:
            fail(4, "tampered_identity", "corpus_identity")
        corpus[source["path"].casefold()] = source
    queries = {q["query_id"]: q["requirement"] for q in value["queries"]}
    expected_queries = sorted([{"query_id": "query-" + digest(r), "requirement": r} for r in value["request"]["requirements"]], key=lambda q:q["query_id"])
    if value["queries"] != expected_queries or value["corpus"] != sorted(value["corpus"], key=lambda s:s["path"]):
        fail(4, "tampered_identity", "query_or_corpus_identity")
    hits = value["nominations"]
    if hits != sorted(hits, key=lambda h:(-h["score"], h["path"], h["byte_start"], h["byte_end"], h["query_id"])):
        fail(4, "tampered_identity", "nomination_order")
    ids = set()
    for hit in hits:
        relative_path(hit["path"])
        source = corpus.get(hit["path"].casefold())
        if (source is None or source["path"] != hit["path"] or source["sha256"] != hit["source_sha256"] or not 0 <= hit["byte_start"] < hit["byte_end"] <= source["size_bytes"] or hit["line_end"] < hit["line_start"]
            or hit["nomination_id"] in ids or hit["nomination_id"] != "hit-" + digest({k:v for k,v in hit.items() if k != "nomination_id"})):
            fail(4, "tampered_identity", "nomination_identity")
        ids.add(hit["nomination_id"])
        policy = value["request"]["resource_policy"]
        if len(hit["excerpt"].encode("utf-8")) > policy["max_excerpt_bytes"] or hit["byte_end"] - hit["byte_start"] > policy["max_range_bytes"]:
            fail(4, "tampered_identity", "range_budget")
        for match in hit["matches"]:
            q = queries.get(match["query_id"])
            if q is None or match["requirement_id"] != q["requirement_id"] or match["requested_role"] != q["requested_role"]:
                fail(4, "tampered_identity", "match_reference")
    if (value["completeness"] == "partial") != bool(value["truncations"]):
        fail(4, "tampered_identity", "completeness")
    return raw, value


def verify(path, project, map_root, record_path=None):
    raw, value = read_bundle(path)
    # Output artifacts and equivalent request sidecars are excluded during replay.
    ctx = Context(value["request"], project, map_root, record_path=record_path, output=Path(path).parent)
    if ctx.finder != value["finder"]:
        fail(4, "stale_identity", "finder_identity")
    fresh = ctx.build()
    if fresh != value:
        fail(4, "stale_identity", "corpus_or_source_identity")
    return raw, value

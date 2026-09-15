"""Closed contract validation and safe diagnostics. Standard library only."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/evidence-nomination/v1"
SKILL = ROOT / "skills/analyze-project-claims"
SCHEMA_NAMES = ("bundle", "claim-candidate", "component-candidate", "gap-request", "selection")
MAX_JSON_BYTES = 8 * 1024 * 1024
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b"),
    re.compile(r"[\"']?\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)[\"']?\s*[:=]\s*[\"']?[^\s,;\"']{8,}", re.I),
)


class Failure(Exception):
    def __init__(self, exit_code, code, reason, *, changed=False, artifacts=()):
        self.exit_code = exit_code
        self.code = code
        self.reason = reason  # Only static machine codes, never untrusted text.
        self.changed = changed
        self.artifacts = list(artifacts)
        super().__init__(code)


def fail(exit_code, code, reason):
    raise Failure(exit_code, code, reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha(canonical(value))


def secret(text):
    return any(p.search(text) for p in SECRET_PATTERNS)


def safe_text(text, multiline=False):
    return all(unicodedata.category(c) not in {"Cc", "Cf", "Cs"} or (multiline and c in "\t\r\n") for c in text)


def inspect_json(value, depth=0):
    if depth > 64:
        fail(2, "invalid_input", "json_depth")
    if type(value) in (dict, list):
        if len(value) > 25000:
            fail(2, "invalid_input", "json_size")
        items = list(value) + list(value.values()) if isinstance(value, dict) else value
        for item in items:
            inspect_json(item, depth + 1)
    elif isinstance(value, str):
        if not safe_text(value, multiline=True) or secret(value):
            fail(2, "safety_refusal", "unsafe_text")
    elif type(value) not in (int, bool, type(None)):
        fail(2, "invalid_input", "json_number")


def parse_json(raw):
    if len(raw) > MAX_JSON_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        fail(2, "invalid_input", "json_size_or_bom")
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                fail(2, "invalid_input", "duplicate_json_key")
            result[k] = v
        return result
    def bad_number(_):
        fail(2, "invalid_input", "json_number")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_float=bad_number, parse_constant=bad_number)
    except (UnicodeError, ValueError, RecursionError):
        fail(2, "invalid_input", "json_syntax")
    inspect_json(value)
    return value


class Deadline:
    def __init__(self, seconds):
        self.until = time.monotonic() + seconds

    def check(self):
        if time.monotonic() >= self.until:
            fail(3, "timeout", "deadline")


class Schemas:
    """Interpret only the pinned schemas' assertion vocabulary, never remote refs."""
    KEYWORDS = {"$schema", "$id", "$defs", "$ref", "title", "description", "default", "type", "const", "enum", "required", "properties", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "minimum", "maximum", "oneOf", "anyOf", "allOf", "format"}

    def __init__(self):
        self.documents = {}
        for name in SCHEMA_NAMES:
            path = CONTRACT / (name + ".schema.json")
            self.documents[path] = json.loads(path.read_bytes())
        for name in ("scan-record-v2.schema.json", "component-map-observation.schema.json"):
            path = SKILL / "references" / name
            self.documents[path] = json.loads(path.read_bytes())

    def validate(self, value, name):
        try:
            self._check(value, CONTRACT / (name + ".schema.json"))
        except (ValueError, KeyError, TypeError, RecursionError):
            fail(2, "invalid_input", "schema")

    def _check(self, value, path, node=None):
        node = self.documents[path] if node is None else node
        if set(node) - self.KEYWORDS:
            fail(4, "stale_identity", "schema_vocabulary")
        if "$ref" in node:
            filename, _, pointer = node["$ref"].partition("#")
            if ":" in filename:
                fail(4, "stale_identity", "schema_reference")
            target = (path.parent / filename).resolve() if filename else path
            if target not in self.documents:
                fail(4, "stale_identity", "schema_reference")
            referred = self.documents[target]
            for part in pointer.lstrip("/").split("/") if pointer else []:
                referred = referred[part.replace("~1", "/").replace("~0", "~")]
            self._check(value, target, referred)
        for key in ("oneOf", "anyOf", "allOf"):
            if key in node:
                successes = 0
                for branch in node[key]:
                    try:
                        self._check(value, path, branch)
                        successes += 1
                    except ValueError:
                        pass
                if (key == "oneOf" and successes != 1) or (key == "anyOf" and not successes) or (key == "allOf" and successes != len(node[key])):
                    raise ValueError(key)
        if "const" in node and (type(value) is not type(node["const"]) or value != node["const"]):
            raise ValueError("const")
        if "enum" in node and not any(type(value) is type(x) and value == x for x in node["enum"]):
            raise ValueError("enum")
        types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
        expected = node.get("type")
        if expected and type(value) not in [types[k] for k in (expected if isinstance(expected, list) else [expected])]:
            raise ValueError("type")
        if isinstance(value, dict):
            props = node.get("properties", {})
            if set(node.get("required", [])) - set(value) or (node.get("additionalProperties") is False and set(value) - set(props)):
                raise ValueError("keys")
            for key in value.keys() & props.keys():
                self._check(value[key], path, props[key])
        if isinstance(value, list):
            if len(value) < node.get("minItems", 0) or len(value) > node.get("maxItems", float("inf")):
                raise ValueError("array size")
            if node.get("uniqueItems") and len({canonical(x) for x in value}) != len(value):
                raise ValueError("uniqueItems")
            for item in value:
                if "items" in node:
                    self._check(item, path, node["items"])
        if isinstance(value, str):
            if len(value) < node.get("minLength", 0) or len(value) > node.get("maxLength", float("inf")):
                raise ValueError("string size")
            if "pattern" in node and not re.search(node["pattern"], value):
                raise ValueError("pattern")
            if "format" in node and (node["format"] != "uri" or not re.match(r"^https://[^/ ]+", value)):
                raise ValueError("format")
        if type(value) is int and (value < node.get("minimum", float("-inf")) or value > node.get("maximum", float("inf"))):
            raise ValueError("number range")


def relative_path(value, allow_dot=False):
    if allow_dot and value == ".":
        return value
    if not isinstance(value, str) or not value or len(value) > 500 or not safe_text(value) or secret(value):
        fail(2, "safety_refusal", "path_policy")
    parts = value.split("/")
    if any(not p or p in (".", "..") or p.endswith((" ", ".")) or "\\" in p or ":" in p for p in parts):
        fail(2, "safety_refusal", "path_policy")
    for part in parts:
        stem = part.split(".")[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(?:COM|LPT)[1-9???]", stem):
            fail(2, "safety_refusal", "path_policy")
    return value


def normalize_request(value, schemas):
    value = copy.deepcopy(value)
    if not isinstance(value, dict):
        fail(2, "invalid_input", "request")
    try:
        for r in value["requirements"]:
            for key in ("all_terms", "any_terms", "exclude_terms"):
                terms = r[key]
                if not isinstance(terms, list) or any(not isinstance(t, str) or not safe_text(t) for t in terms):
                    fail(2, "invalid_input", "query_terms")
                r[key] = sorted(set(terms))
        value["requirements"].sort(key=lambda r: r["requirement_id"])
        value["allowed_roots"].sort()
    except (KeyError, TypeError, AttributeError):
        fail(2, "invalid_input", "request")
    schemas.validate(value, "gap-request")
    identifiers = list(value["map"].values()) + [r["requirement_id"] for r in value["requirements"]]
    identifiers += [v for v in value["target"].values() if isinstance(v, str)]
    identifiers += list(value["target"]["element_ref"].values())
    if any(not safe_text(v) for v in identifiers):
        fail(2, "invalid_input", "identifier_controls")
    roots = value["allowed_roots"]
    folded = []
    for root in roots:
        relative_path(root, allow_dot=True)
        key = root.casefold()
        if any(key == p or p == "." or key == "." or key.startswith(p + "/") or p.startswith(key + "/") for p in folded):
            fail(2, "invalid_input", "overlapping_roots")
        folded.append(key)
    ids = [r["requirement_id"] for r in value["requirements"]]
    if len(ids) != len(set(ids)):
        fail(2, "invalid_input", "duplicate_requirement_id")
    p = value["resource_policy"]
    if p["max_file_bytes"] > p["max_total_bytes"] or p["max_excerpt_bytes"] > p["max_range_bytes"] or p["max_per_requirement"] > p["max_nominations"] or len(ids) > p["max_requirements"]:
        fail(2, "invalid_input", "resource_policy")
    return value

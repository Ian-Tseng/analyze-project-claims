"""Test-only evaluator for the JSON Schema keywords used by frozen fixtures.

This is not a production input validator or a general JSON Schema implementation.
Unknown assertion keywords fail the test rather than silently reducing coverage.
No remote refs are fetched.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def check_schema(value, path, schema=None):
    path = Path(path).resolve()
    node = load(path) if schema is None else schema
    allowed = {"$schema", "$id", "$defs", "$ref", "title", "description", "default", "type", "const", "enum", "required", "properties", "additionalProperties", "items", "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "minimum", "maximum", "oneOf", "anyOf", "allOf", "format"}
    if set(node) - allowed:
        raise AssertionError(f"Unsupported schema keywords: {set(node) - allowed}")
    if "$ref" in node:
        filename, _, pointer = node["$ref"].partition("#")
        if ":" in filename:
            raise AssertionError("Remote references are forbidden")
        target = (path.parent / filename).resolve() if filename else path
        repo = Path(__file__).resolve().parents[1]
        if not target.is_relative_to(repo):
            raise AssertionError("Reference escaped repository")
        referred = load(target)
        for part in pointer.lstrip("/").split("/") if pointer else []:
            referred = referred[part.replace("~1", "/").replace("~0", "~")]
        check_schema(value, target, referred)
    for key in ("oneOf", "anyOf", "allOf"):
        if key in node:
            successes = 0
            for branch in node[key]:
                try:
                    check_schema(value, path, branch)
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
        if set(node.get("required", [])) - set(value):
            raise ValueError("required")
        properties = node.get("properties", {})
        if node.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError("additionalProperties")
        for key in value.keys() & properties.keys():
            check_schema(value[key], path, properties[key])
    if isinstance(value, list):
        if len(value) < node.get("minItems", 0) or len(value) > node.get("maxItems", float("inf")):
            raise ValueError("array size")
        if node.get("uniqueItems") and len({canonical(x) for x in value}) != len(value):
            raise ValueError("uniqueItems")
        if "items" in node:
            for item in value:
                check_schema(item, path, node["items"])
    if isinstance(value, str):
        if len(value) < node.get("minLength", 0) or len(value) > node.get("maxLength", float("inf")):
            raise ValueError("string length")
        if "pattern" in node and not re.search(node["pattern"], value):
            raise ValueError("pattern")
        if "format" in node and (node["format"] != "uri" or not re.match(r"^https://[^/ ]+", value)):
            raise ValueError("format")
    if type(value) is int and (value < node.get("minimum", float("-inf")) or value > node.get("maximum", float("inf"))):
        raise ValueError("number range")

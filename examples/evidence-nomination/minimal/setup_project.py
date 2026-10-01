"""Create a fresh SYNTHETIC walkthrough copy for the current skill identity.

Never accept or refresh a real map. The checked-in fixture and golden history
remain byte-for-byte unchanged; an existing destination is never overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

EXAMPLE = Path(__file__).resolve().parent
ROOT = EXAMPLE.parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def fixture_payloads():
    """Return current identities for this exact explicitly synthetic template."""
    value = json.loads((EXAMPLE / "project/map/accepted-map.json").read_bytes())
    if value["authority"] != ["test-owned component map"] or value["origin_scan_id"] != "fixture-scan":
        raise ValueError("Only the explicit synthetic fixture is allowed")
    integrity = value.pop("integrity")
    if integrity != {"canonical_payload_sha256": hashlib.sha256(canonical(value)).hexdigest()}:
        raise ValueError("Synthetic template integrity differs")
    value["skill_sha256"] = hashlib.sha256((ROOT / "skills/analyze-project-claims/SKILL.md").read_bytes()).hexdigest()
    value["integrity"] = {"canonical_payload_sha256": hashlib.sha256(canonical(value)).hexdigest()}
    raw = canonical(value) + b"\n"
    request = json.loads((EXAMPLE / "request.json").read_bytes())
    request["map"] = {"map_id": value["map_id"],
                      "canonical_payload_sha256": value["integrity"]["canonical_payload_sha256"],
                      "file_sha256": hashlib.sha256(raw).hexdigest()}
    return raw, request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory outside the checked-in example")
    args = parser.parse_args()
    try:
        output = args.output.resolve()
        if output.is_relative_to(EXAMPLE):
            raise ValueError("Preserve checked-in fixture history")
        map_raw, request = fixture_payloads()
        output.mkdir(parents=True, exist_ok=False)
        project = output / "project"
        shutil.copytree(EXAMPLE / "project", project,
                        ignore=shutil.ignore_patterns(".analyze-project-claims", "__pycache__"))
        (project / "map/accepted-map.json").write_bytes(map_raw)
        (output / "request.json").write_bytes(canonical(request) + b"\n")
    except (OSError, ValueError, KeyError, TypeError):
        print("Synthetic setup refused: use the intact example and a new directory outside it.", file=sys.stderr)
        return 2
    print(json.dumps({"status": "synthetic_fixture_prepared", "project_root": str(project),
                      "request": str(output / "request.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

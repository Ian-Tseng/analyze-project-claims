"""Bind the prerecorded SYNTHETIC example review; never review a real project."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = args.bundle.read_bytes()
        bundle = json.loads(raw)
        expected = json.loads((EXAMPLE / "golden/bundle.json").read_bytes())
        # Runtime/Unicode identities can differ; the prerecorded review only
        # applies to these exact request, corpus, queries, and nominations.
        for key in ("request", "corpus", "queries", "nominations", "exclusions", "truncations", "completeness"):
            if bundle[key] != expected[key]:
                raise ValueError("example differs")
        if args.output.absolute().parent != args.bundle.absolute().parent:
            raise ValueError("review must be beside bundle")
        selection = json.loads((EXAMPLE / "review.json").read_bytes())
        selection["bundle"] = {"bundle_id": bundle["bundle_id"],
                               "canonical_payload_sha256": bundle["canonical_payload_sha256"],
                               "file_sha256": hashlib.sha256(raw).hexdigest()}
        encoded = json.dumps(selection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        with args.output.open("xb") as stream:
            stream.write(encoded)
    except (OSError, ValueError, KeyError, TypeError):
        print("Example review refused: use the unchanged synthetic fixture and a new sibling output.", file=sys.stderr)
        return 2
    print(json.dumps({"status": "synthetic_review_prepared", "output": str(args.output)}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

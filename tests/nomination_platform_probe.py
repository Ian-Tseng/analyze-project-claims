"""Emit comparable component nomination/compile bytes on real host platforms."""
import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from nomination_runtime_fixtures import refresh_component_map

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "contracts/evidence-nomination/v1/golden"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    with tempfile.TemporaryDirectory(prefix="nomination-platform-") as temporary:
        project = Path(temporary).resolve() / "project"
        shutil.copytree(GOLDEN / "project", project)
        output = project / ".analyze-project-claims/nominations"
        request = project / "request.json"
        request.write_bytes(canonical(refresh_component_map(project, json.loads((GOLDEN / "gap-request.json").read_bytes()))))
        scope = ["--project-root", str(project), "--map-root", str(project / "map")]
        def run(command, *arguments):
            result = subprocess.run([sys.executable, "-I", str(ROOT / "scripts/evidence_nomination.py"), command,
                                     *map(str, arguments), "--format", "json"], capture_output=True, text=True, encoding="utf-8", timeout=60)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            return json.loads(result.stdout)
        nominated = run("nominate", "--request", request, "--out-dir", output, *scope)
        bundle = Path(nominated["artifact_path"])
        selection_path = Path(nominated["selection_path"])
        draft = selection_path.read_bytes()
        selection = json.loads((GOLDEN / "selection.json").read_bytes())
        selection["bundle"] = json.loads(draft)["bundle"]
        selection_path.write_bytes(canonical(selection))
        candidate = output / "candidate.json"
        run("compile", "--bundle", bundle, "--selection", selection_path, "--output", candidate, *scope)
        payload = output / "payload.json"
        run("handoff", "--bundle", bundle, "--selection", selection_path, "--candidate", candidate, "--output", payload, *scope)
        run("verify", "--bundle", bundle, *scope)
        report = {"platform": platform.platform(), "python": platform.python_version(), "status": "passed",
                  "artifact_sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in
                                      (("bundle", bundle.read_bytes()), ("selection_draft", draft),
                                       ("reviewed_selection", selection_path.read_bytes()), ("candidate", candidate.read_bytes()),
                                       ("payload", payload.read_bytes()))}}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

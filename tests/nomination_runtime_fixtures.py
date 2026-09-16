"""Fresh test-owned recorder authority; frozen T1 history remains untouched."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def refresh_component_map(project, request):
    """Rebind only a test-owned fixture copy; never mutate frozen or real maps."""
    project = Path(project).resolve()
    if project.is_relative_to(ROOT / "contracts") or project == ROOT:
        raise AssertionError("Refuse mutation of historical or repository authority")
    path = project / "map/accepted-map.json"
    value = json.loads(path.read_bytes())
    if value["authority"] != ["test-owned component map"]:
        raise AssertionError("Only the explicit synthetic fixture is allowed")
    value["skill_sha256"] = hashlib.sha256((ROOT / "skills/analyze-project-claims/SKILL.md").read_bytes()).hexdigest()
    value.pop("integrity")
    canonical = lambda data: json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    value["integrity"] = {"canonical_payload_sha256": hashlib.sha256(canonical(value)).hexdigest()}
    raw = canonical(value) + b"\n"
    path.write_bytes(raw)
    request["map"] = {"map_id": value["map_id"], "canonical_payload_sha256": value["integrity"]["canonical_payload_sha256"], "file_sha256": hashlib.sha256(raw).hexdigest()}
    return request


def refresh_claim_record(project, request):
    request = refresh_component_map(project, request)
    with tempfile.TemporaryDirectory(prefix="native-record-", dir=project) as temporary:
        result = subprocess.run([sys.executable, str(ROOT / "skills/analyze-project-claims/scripts/record_scan.py"),
                                 "append", "--record", str(project / "record-input.json"),
                                 "--project-root", str(project), "--map-root", str(project / "map"),
                                 "--log-dir", temporary], capture_output=True, text=True, encoding="utf-8", timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        raw = Path(json.loads(result.stdout)["log"]).read_bytes()
    (project / "record.json").write_bytes(raw)
    record = json.loads(raw)
    request["target"]["record_sha256"] = hashlib.sha256(raw).hexdigest()
    request["target"]["scan_id"] = record["scan"]["scan_id"]
    return request

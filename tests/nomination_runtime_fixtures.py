"""Fresh test-owned recorder authority; frozen T1 history remains untouched."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def refresh_claim_record(project, request):
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

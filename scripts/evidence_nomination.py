#!/usr/bin/env python3
"""Repository shortcut to the packaged local evidence nominator."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "skills/analyze-project-claims/scripts/evidence_nomination.py"), run_name="__main__")

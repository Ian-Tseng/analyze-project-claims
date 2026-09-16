"""Compatibility import for repository tests; implementation lives in the package."""
from pathlib import Path
__path__ = [str(Path(__file__).resolve().parents[2] / "skills/analyze-project-claims/scripts/_internal/evidence_nomination")]

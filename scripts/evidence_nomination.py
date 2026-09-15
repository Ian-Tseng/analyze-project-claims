#!/usr/bin/env python3
"""Development entry point. This command is not installed until the T6 release gate."""
import os
import sys

# Ignore project/PYTHONPATH modules during finder execution. Python startup hooks
# run before this script; use python -I when the interpreter environment is untrusted.
sys.dont_write_bytecode = True
_script_dir = os.path.dirname(os.path.abspath(__file__))
_prefixes = (os.path.abspath(sys.base_prefix), os.path.abspath(sys.prefix))
_safe_paths = []
for _path in sys.path:
    if not _path or "site-packages" in _path or "dist-packages" in _path:
        continue
    try:
        if any(os.path.commonpath((os.path.abspath(_path), p)) == p for p in _prefixes):
            _safe_paths.append(_path)
    except ValueError:
        pass
sys.path[:] = [_script_dir] + _safe_paths
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")

from _nomination.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

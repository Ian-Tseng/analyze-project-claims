"""Opt-in exact-map/input guards for nomination handoffs to native commands."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
FIELDS = ("expected_map_id", "expected_map_canonical_sha256", "expected_map_file_sha256")


class MapGuardError(ValueError):
    """A guarded operation must stop before producing authority artifacts."""


def add_guard_arguments(parser):
    parser.add_argument("--expected-map-id")
    parser.add_argument("--expected-map-canonical-sha256")
    parser.add_argument("--expected-map-file-sha256")
    parser.add_argument("--expected-input-sha256")


def expected_identity(args):
    values = tuple(getattr(args, key, None) for key in FIELDS)
    if not any(v is not None for v in values):
        if getattr(args, "expected_input_sha256", None) is not None:
            raise MapGuardError("EXPECTED_MAP_REQUIRED: input guard requires all three map guards")
        return None
    patterns = (r"component-map-[0-9a-f]{12}", r"[0-9a-f]{64}", r"[0-9a-f]{64}")
    if any(not isinstance(v, str) or re.fullmatch(p, v) is None for p, v in zip(patterns, values)):
        raise MapGuardError("EXPECTED_MAP_INVALID: supply all three valid map identities")
    expected_input = getattr(args, "expected_input_sha256", None)
    if expected_input is not None and re.fullmatch(r"[0-9a-f]{64}", expected_input) is None:
        raise MapGuardError("EXPECTED_INPUT_INVALID: input digest must be SHA-256")
    return values


def snapshot(path, *, maximum=MAX_BYTES):
    """Bound one ordinary file read; parse exactly the bytes that were hashed."""
    maximum = min(maximum, MAX_BYTES)
    path = Path(os.path.abspath(path))
    if str(path).startswith(("//", "\\\\")):
        raise MapGuardError("GUARDED_PATH_UNSAFE: network paths are excluded")
    try:
        for part in (path, *path.parents):
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise MapGuardError("GUARDED_PATH_UNSAFE: link or reparse path")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise MapGuardError("GUARDED_INPUT_INVALID: bounded regular JSON file required")
            raw = handle.read(maximum + 1)
            after = os.fstat(handle.fileno())
        current = path.lstat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        if len(raw) > maximum or signature(before) != signature(after) or signature(before) != signature(current):
            raise MapGuardError("GUARDED_INPUT_CHANGED: file changed while reading")
        def pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError("duplicate key")
                value[key] = item
            return value
        def nonfinite(value):
            raise ValueError("nonfinite")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
        if not isinstance(value, dict):
            raise ValueError("object required")
        return value, hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, MapGuardError):
            raise
        raise MapGuardError("GUARDED_INPUT_INVALID: cannot read a stable local JSON object") from None


def guarded_map(path, args, validate, *, maximum=MAX_BYTES):
    expected = expected_identity(args)
    if expected is None:
        return None
    value, file_sha = snapshot(path, maximum=maximum)
    try:
        validate(value, "guarded accepted-map.json")
    except ValueError:
        raise MapGuardError("EXPECTED_MAP_INVALID: accepted map fails its native contract") from None
    current = (value.get("map_id"), value.get("integrity", {}).get("canonical_payload_sha256"), file_sha)
    if value.get("map_state") != "accepted" or current != expected:
        raise MapGuardError("EXPECTED_MAP_MISMATCH: accepted map changed; nominate and review again")
    return value, file_sha


def guarded_input(path, args, loader, *, maximum=MAX_BYTES):
    expected_identity(args)
    expected = getattr(args, "expected_input_sha256", None)
    if expected is None:
        return loader(path)
    value, current = snapshot(path, maximum=maximum)
    if current != expected:
        raise MapGuardError("EXPECTED_INPUT_MISMATCH: payload changed after handoff")
    return value

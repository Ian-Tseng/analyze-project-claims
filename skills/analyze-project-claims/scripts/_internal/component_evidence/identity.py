'''Build and verify the content identity of the embedded evidence engine.'''

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from . import (
    ENGINE_NAME,
    ENGINE_VERSION,
    MAP_SCHEMA_VERSION,
    PROVIDER_KIND,
    RECEIPT_PROTOCOL_VERSION,
)


DESCRIPTOR_PATH = Path('references/component-evidence-engine.json')
INTERNAL_ROOT = Path('scripts/_internal/component_evidence')
TRANSIENT_SUFFIXES = {'.pyc', '.pyo'}
CONTRACT_PATHS = {
    'assets/component-map-observation.template.json',
    'assets/component-map.template.json',
    'references/component-evidence-protocol.md',
    'references/component-map-observation.schema.json',
    'references/component-map-receipt.schema.json',
    'references/component-map.schema.json',
    'scripts/_internal/__init__.py',
    'scripts/reconcile_component_map.py',
}
EXPECTED_KEYS = {
    'algorithm',
    'engine_digest',
    'engine_name',
    'engine_version',
    'files',
    'map_schema_version',
    'provider_kind',
    'receipt_protocol_version',
    'schema_version',
}
SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')


class EngineIdentityError(ValueError):
    '''Raised when the embedded engine descriptor or bytes are invalid.'''


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _engine_paths(skill_root: Path) -> list[str]:
    internal_root = skill_root / INTERNAL_ROOT
    paths = set(CONTRACT_PATHS)
    if not internal_root.is_dir():
        raise EngineIdentityError('embedded engine directory is missing')
    for path in internal_root.rglob('*'):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_root)
        if '__pycache__' in relative.parts or path.suffix.lower() in TRANSIENT_SUFFIXES:
            continue
        paths.add(relative.as_posix())
    return sorted(paths)


def _validate_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise EngineIdentityError('engine file path must be a non-empty string')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or value != path.as_posix():
        raise EngineIdentityError(f'invalid engine file path: {value!r}')
    return value


def build_engine_descriptor(skill_root: Path) -> dict[str, Any]:
    '''Return the canonical descriptor implied by the current engine bytes.'''
    skill_root = skill_root.resolve()
    files: list[dict[str, str]] = []
    for relative in _engine_paths(skill_root):
        path = skill_root / relative
        if not path.is_file() or path.is_symlink():
            raise EngineIdentityError(f'engine file is missing or unsafe: {relative}')
        files.append({'path': relative, 'sha256': _sha256_file(path)})
    descriptor: dict[str, Any] = {
        'schema_version': 1,
        'provider_kind': PROVIDER_KIND,
        'engine_name': ENGINE_NAME,
        'engine_version': ENGINE_VERSION,
        'map_schema_version': MAP_SCHEMA_VERSION,
        'receipt_protocol_version': RECEIPT_PROTOCOL_VERSION,
        'algorithm': 'sha256',
        'files': files,
    }
    descriptor['engine_digest'] = _sha256_bytes(_canonical(descriptor))
    return descriptor


def _load_descriptor(skill_root: Path) -> dict[str, Any]:
    path = skill_root / DESCRIPTOR_PATH
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise EngineIdentityError('embedded engine descriptor is missing or invalid') from exc
    if not isinstance(value, dict):
        raise EngineIdentityError('embedded engine descriptor must be an object')
    return value


def verify_engine_descriptor(skill_root: Path) -> dict[str, Any]:
    '''Verify descriptor metadata, file coverage, file hashes, and engine digest.'''
    skill_root = skill_root.resolve()
    descriptor = _load_descriptor(skill_root)
    if set(descriptor) != EXPECTED_KEYS:
        raise EngineIdentityError('embedded engine descriptor has unknown or missing fields')
    expected_metadata = {
        'schema_version': 1,
        'provider_kind': PROVIDER_KIND,
        'engine_name': ENGINE_NAME,
        'engine_version': ENGINE_VERSION,
        'map_schema_version': MAP_SCHEMA_VERSION,
        'receipt_protocol_version': RECEIPT_PROTOCOL_VERSION,
        'algorithm': 'sha256',
    }
    for field, expected in expected_metadata.items():
        if descriptor.get(field) != expected:
            raise EngineIdentityError(f'embedded engine descriptor {field} mismatch')

    entries = descriptor.get('files')
    if not isinstance(entries, list):
        raise EngineIdentityError('embedded engine descriptor files must be a list')
    declared_paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256'}:
            raise EngineIdentityError('embedded engine descriptor file entry is invalid')
        relative = _validate_relative_path(entry.get('path'))
        digest = entry.get('sha256')
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise EngineIdentityError(f'embedded engine file digest is invalid: {relative}')
        path = skill_root / relative
        if not path.is_file() or path.is_symlink():
            raise EngineIdentityError(f'engine file is missing or unsafe: {relative}')
        if _sha256_file(path) != digest:
            raise EngineIdentityError(f'engine file digest mismatch: {relative}')
        declared_paths.append(relative)

    actual_paths = _engine_paths(skill_root)
    if declared_paths != sorted(set(declared_paths)) or declared_paths != actual_paths:
        raise EngineIdentityError('embedded engine descriptor file set mismatch')

    engine_digest = descriptor.get('engine_digest')
    if not isinstance(engine_digest, str) or SHA256_PATTERN.fullmatch(engine_digest) is None:
        raise EngineIdentityError('embedded engine digest is invalid')
    digest_payload = dict(descriptor)
    digest_payload.pop('engine_digest')
    if _sha256_bytes(_canonical(digest_payload)) != engine_digest:
        raise EngineIdentityError('embedded engine descriptor digest mismatch')
    return descriptor


def verified_engine_summary(skill_root: Path) -> dict[str, Any]:
    descriptor = verify_engine_descriptor(skill_root)
    return {
        'status': 'verified',
        'provider_kind': descriptor['provider_kind'],
        'engine_name': descriptor['engine_name'],
        'engine_version': descriptor['engine_version'],
        'map_schema_version': descriptor['map_schema_version'],
        'receipt_protocol_version': descriptor['receipt_protocol_version'],
        'engine_digest': descriptor['engine_digest'],
    }

"""Bounded no-follow reads and atomic, exclusive artifact publication."""
from __future__ import annotations

import contextlib
import errno
import os
import stat
import tempfile
from pathlib import Path

from .common import Failure, fail, relative_path

from _internal.component_evidence import local_io as _io

linked = _io.linked
signature = _io.signature
if os.name == "nt":
    win_open = _io.win_open
    _close = _io._close


def absolute(path):
    try:
        result = _io.absolute(path)
    except _io.LocalIOError as exc:
        fail(exc.exit_code, exc.code, exc.reason)
    if len(result.parts) > 1:
        relative_path("/".join(result.parts[1:]), allow_dot=True)
    return result


@contextlib.contextmanager
def parent_guard(path):
    try:
        with _io.parent_guard(absolute(path)) as parent:
            yield parent
    except _io.LocalIOError as exc:
        fail(exc.exit_code, exc.code, exc.reason)


def entry_stat(path, missing_ok=False):
    path = absolute(path)
    with parent_guard(path) as parent:
        try:
            return os.stat(path if parent is None else path.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise


def directory(path):
    info = entry_stat(path)
    if linked(info) or not stat.S_ISDIR(info.st_mode):
        fail(2, "safety_refusal", "directory")
    return absolute(path)


def safe_read(path, maximum, deadline=None):
    try:
        return _io.safe_read(absolute(path), maximum, deadline)
    except _io.LocalIOError as exc:
        fail(exc.exit_code, exc.code, exc.reason)


def list_names(path, remaining, deadline):
    path = absolute(path)
    names = []
    with parent_guard(path) as parent:
        if os.name == "nt":
            handle = win_open(path, directory=True)
            fd = None
        else:
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            handle = None
        try:
            with os.scandir(path if fd is None else fd) as entries:
                for entry in entries:
                    deadline.check()
                    names.append(entry.name)
                    if len(names) > remaining:
                        fail(2, "safety_refusal", "traversal_limit")
        finally:
            if fd is not None:
                os.close(fd)
            if handle is not None:
                _close(handle)
    return sorted(names)


def make_directories(path):
    path = absolute(path)
    cursor = Path(path.anchor)
    created = []
    try:
        for part in path.parts[1:]:
            cursor /= part
            with parent_guard(cursor) as parent:
                try:
                    os.mkdir(cursor if parent is None else cursor.name, dir_fd=parent)
                    created.append(str(cursor))
                except FileExistsError:
                    pass
                info = os.stat(cursor if parent is None else cursor.name, dir_fd=parent, follow_symlinks=False)
                if linked(info) or not stat.S_ISDIR(info.st_mode):
                    fail(2, "safety_refusal", "output_directory")
    except Failure as exc:
        raise Failure(5 if created else exc.exit_code,
                      "recovery_required" if created else exc.code,
                      exc.reason, changed=bool(created), artifacts=created) from None
    return created


def atomic_create(path, data):
    """Exclusive publication, retaining and verifying the written file identity.

    Competing same-user writes may leave recovery artifacts. No success receipt
    is returned for a substituted temporary file or changed parent directory.
    """
    path = absolute(path)
    temporary = None
    published = False
    created = False
    owned = None
    try:
        with parent_guard(path) as parent:
            try:
                if parent is None:
                    fd, name = tempfile.mkstemp(prefix=".nomination-", suffix=".tmp", dir=path.parent)
                    temporary = Path(name)
                else:
                    import secrets
                    temporary = ".nomination-" + secrets.token_hex(16) + ".tmp"
                    fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                created = True
                with os.fdopen(fd, "w+b") as stream:
                    info = os.fstat(stream.fileno())
                    owned = (info.st_dev, info.st_ino)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                    before = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                    if linked(before) or (before.st_dev, before.st_ino) != owned:
                        fail(5, "recovery_required", "temporary_changed")
                    os.link(temporary, path if parent is None else path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    published = True
                    current = os.stat(path if parent is None else path.name, dir_fd=parent, follow_symlinks=False)
                    stream.seek(0)
                    if linked(current) or (current.st_dev, current.st_ino) != owned or stream.read(len(data) + 1) != data:
                        fail(5, "recovery_required", "publication_changed")
            finally:
                if temporary is not None:
                    try:
                        current = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                        if linked(current) or (current.st_dev, current.st_ino) != owned:
                            fail(5, "recovery_required", "temporary_changed")
                        os.unlink(temporary, dir_fd=parent)
                        temporary = None
                    except FileNotFoundError:
                        temporary = None
    except (OSError, Failure) as exc:
        artifacts = ([str(path)] if published else []) + ([str(path.parent / temporary)] if temporary is not None else [])
        if published or temporary is not None:
            raise Failure(5, "recovery_required", exc.reason if isinstance(exc, Failure) else "publication_io",
                          changed=True, artifacts=artifacts) from None
        if created and isinstance(exc, Failure) and exc.reason == "parent_changed":
            raise Failure(5, "recovery_required", "parent_changed", changed=True, artifacts=[str(path)]) from None
        raise

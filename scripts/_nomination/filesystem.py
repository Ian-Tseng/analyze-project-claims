"""Bounded no-follow reads and atomic, exclusive artifact publication."""
from __future__ import annotations

import contextlib
import errno
import os
import stat
import tempfile
from pathlib import Path

from .common import Failure, fail, relative_path

REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & REPARSE)


def absolute(path):
    raw = os.fspath(path)
    if raw.startswith(("\\\\", "//")):
        fail(2, "safety_refusal", "network_path")
    result = Path(os.path.abspath(raw))
    if len(result.parts) > 1:
        relative_path("/".join(result.parts[1:]), allow_dot=True)
    if os.name == "nt" and _kernel.GetDriveTypeW(str(result.anchor)) == 4:
        fail(2, "safety_refusal", "network_drive")
    return result


def signature(info):
    base = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    # Windows lstat and CRT fstat expose different ctime meanings on Python 3.12.
    # File handles deny writes/deletion there; do not compare creation to change time.
    return base if os.name == "nt" else base + (info.st_ctime_ns,)


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _create = _kernel.CreateFileW
    _create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    _create.restype = wintypes.HANDLE
    _close = _kernel.CloseHandle
    _close.argtypes = (wintypes.HANDLE,)
    _close.restype = wintypes.BOOL
    _kernel.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    _kernel.GetDriveTypeW.restype = wintypes.UINT
    _invalid = ctypes.c_void_p(-1).value

    def win_open(path, directory=False):
        # OPEN_REPARSE_POINT opens the entry, not its target. Omitting SHARE_DELETE
        # pins each directory against rename/replacement while descendants are read.
        handle = _create(str(path), 0x80 if directory else 0x80000000, 3 if directory else 1, None, 3, 0x00200000 | (0x02000000 if directory else 0), None)
        if handle == _invalid:
            raise ctypes.WinError(ctypes.get_last_error())
        retained = False
        try:
            info = os.lstat(path)
            if linked(info) or (directory and not stat.S_ISDIR(info.st_mode)):
                fail(2, "safety_refusal", "link_or_reparse")
            if directory:
                retained = True
                return handle
            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            handle = None
            return fd
        finally:
            if handle is not None and not retained:
                _close(handle)


@contextlib.contextmanager
def parent_guard(path):
    """Pin ordinary parent directories; yield POSIX parent fd or None on Windows."""
    path = absolute(path)
    handles = []
    try:
        if os.name == "nt":
            cursor = Path(path.anchor)
            handles.append(win_open(cursor, directory=True))
            for part in path.parent.parts[1:]:
                cursor /= part
                handles.append(win_open(cursor, directory=True))
            yield None
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            fd = os.open(path.anchor, flags)
            handles.append(fd)
            for part in path.parent.parts[1:]:
                fd = os.open(part, flags, dir_fd=fd)
                handles.append(fd)
            yield fd
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            fail(2, "safety_refusal", "link_or_reparse")
        fail(3, "local_io_retry", "filesystem")
    finally:
        for handle in reversed(handles):
            if os.name == "nt":
                _close(handle)
            else:
                os.close(handle)


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
    path = absolute(path)
    with parent_guard(path) as parent:
        before = os.stat(path if parent is None else path.name, dir_fd=parent, follow_symlinks=False)
        if linked(before) or not stat.S_ISREG(before.st_mode):
            fail(2, "safety_refusal", "regular_file")
        if before.st_size > maximum:
            fail(2, "safety_refusal", "file_size")
        fd = win_open(path) if os.name == "nt" else os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or signature(before) != signature(opened):
                fail(3, "local_io_retry", "unstable_read")
            chunks = []
            total = 0
            while True:
                if deadline:
                    deadline.check()
                chunk = os.read(fd, min(65536, maximum + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum:
                    fail(3, "local_io_retry", "unstable_read")
            after = os.fstat(fd)
            current = os.stat(path if parent is None else path.name, dir_fd=parent, follow_symlinks=False)
            if signature(opened) != signature(after) or signature(after) != signature(current) or linked(current):
                fail(3, "local_io_retry", "unstable_read")
            return b"".join(chunks)
        finally:
            os.close(fd)


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
    """Publish a complete temporary file by exclusive hard link, never replace."""
    path = absolute(path)
    with parent_guard(path) as parent:
        temporary = None
        published = False
        error = None
        try:
            if parent is None:
                fd, name = tempfile.mkstemp(prefix=".nomination-", suffix=".tmp", dir=path.parent)
                temporary = Path(name)
            else:
                import secrets
                temporary = ".nomination-" + secrets.token_hex(16) + ".tmp"
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path if parent is None else path.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            published = True
        except OSError as exc:
            error = exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError:
                    pass
                except OSError:
                    temp_path = path.parent / temporary
                    raise Failure(5, "recovery_required", "temporary_cleanup", changed=True,
                                  artifacts=([str(path)] if published else []) + [str(temp_path)]) from None
        if error:
            raise error

"""Bounded no-follow reads and atomic, exclusive artifact publication."""
from __future__ import annotations

import contextlib
import errno
import os
import stat
import tempfile
import re
import unicodedata
from pathlib import Path

class LocalIOError(Exception):
    def __init__(self, exit_code, code, reason):
        self.exit_code, self.code, self.reason = exit_code, code, reason
        super().__init__(reason)


def fail(exit_code, code, reason):
    raise LocalIOError(exit_code, code, reason)


def relative_path(value, allow_dot=False):
    if allow_dot and value == ".":
        return value
    if not value or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value):
        fail(2, "safety_refusal", "path_policy")
    for part in value.split("/"):
        stem = part.split(".")[0].upper()
        if (not part or part in (".", "..") or part.endswith((" ", "."))
            or any(c in part for c in '\\:<>"|?*')
            or stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
            or re.fullmatch(r"(?:COM|LPT)[1-9\u00b9\u00b2\u00b3]", stem)):
            fail(2, "safety_refusal", "path_policy")
    return value

REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & REPARSE)


def absolute(path):
    raw = os.fspath(path)
    if raw.startswith(("\\\\", "//")):
        fail(2, "safety_refusal", "network_path")
    if ".." in raw.replace("\\", "/").split("/"):
        fail(2, "safety_refusal", "path_policy")
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

    class _FileInformation(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                    ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]

    _get_info = _kernel.GetFileInformationByHandle
    _get_info.argtypes = (wintypes.HANDLE, ctypes.POINTER(_FileInformation))
    _get_info.restype = wintypes.BOOL

    def win_info(handle):
        value = _FileInformation()
        if not _get_info(handle, ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.attributes, (value.volume, value.index_high, value.index_low)

    def win_open(path, directory=False):
        # Inspect the opened entry itself. Directory handles alone do not prove
        # that a pathname remains unchanged; parent_guard checks handle identity.
        handle = _create(str(path), 0x80 if directory else 0x80000000, 3 if directory else 1, None, 3, 0x00200000 | (0x02000000 if directory else 0), None)
        if handle == _invalid:
            raise ctypes.WinError(ctypes.get_last_error())
        retained = False
        try:
            attributes, _ = win_info(handle)
            if attributes & REPARSE or (directory and not attributes & 0x10):
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
def parent_guard(path, *, checkpoints=None):
    """Pin ordinary parent directories; yield POSIX parent fd or None on Windows."""
    path = absolute(path)
    handles = []
    ancestry = []
    def check():
        if os.name == "nt":
            for cursor, pinned in ancestry:
                current = win_open(cursor, directory=True)
                try:
                    if win_info(current) != win_info(pinned):
                        fail(3, "local_io_retry", "parent_changed")
                finally:
                    _close(current)
        else:
            for previous, part, pinned in ancestry:
                current = os.stat(part, dir_fd=previous, follow_symlinks=False)
                expected = os.fstat(pinned)
                if linked(current) or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino):
                    fail(3, "local_io_retry", "parent_changed")
    try:
        if os.name == "nt":
            cursor = Path(path.anchor)
            handles.append(win_open(cursor, directory=True))
            ancestry.append((cursor, handles[-1]))
            for part in path.parent.parts[1:]:
                cursor /= part
                handles.append(win_open(cursor, directory=True))
                ancestry.append((cursor, handles[-1]))
            parent = None
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            fd = os.open(path.anchor, flags)
            handles.append(fd)
            for part in path.parent.parts[1:]:
                previous = fd
                fd = os.open(part, flags, dir_fd=fd)
                handles.append(fd)
                ancestry.append((previous, part, fd))
            parent = fd
        if checkpoints is not None:
            checkpoints.append(check)
        check()
        yield parent
        check()
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
    checkpoints = []
    with parent_guard(path, checkpoints=checkpoints) as parent:
        before = os.stat(path if parent is None else path.name, dir_fd=parent, follow_symlinks=False)
        if linked(before) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            fail(2, "safety_refusal", "regular_file")
        if before.st_size > maximum:
            fail(2, "safety_refusal", "file_size")
        fd = win_open(path) if os.name == "nt" else os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or signature(before) != signature(opened):
                fail(3, "local_io_retry", "unstable_read")
            checkpoints[0]()
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
            if signature(opened) != signature(after) or signature(after) != signature(current) or linked(current) or current.st_nlink != 1:
                fail(3, "local_io_retry", "unstable_read")
            return b"".join(chunks)
        finally:
            os.close(fd)

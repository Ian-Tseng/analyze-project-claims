"""Resolve external executables without consulting the current project directory."""

from __future__ import annotations

import os
from pathlib import Path


class ExecutableResolutionError(RuntimeError):
    """Raised when an external executable cannot be resolved safely."""


def resolve_executable(command: str) -> str:
    """Return an absolute executable path while excluding the current directory."""

    if not isinstance(command, str) or not command.strip():
        raise ExecutableResolutionError("Executable name is empty.")
    requested = Path(command)
    if requested.is_absolute():
        resolved = requested.resolve()
        if not resolved.is_file():
            raise ExecutableResolutionError(f"Executable does not exist: {resolved}")
        if os.name == "nt" and resolved.suffix.lower() not in {".exe", ".com"}:
            raise ExecutableResolutionError("Windows executable must be an .exe or .com file.")
        return str(resolved)
    if "/" in command or "\\" in command or requested.parent != Path(".") or requested.drive:
        raise ExecutableResolutionError("Executable paths must be absolute or a bare command name.")

    current = Path.cwd().resolve()
    path_value = os.environ.get("PATH", os.defpath)
    suffixes = [""]
    if os.name == "nt":
        suffixes = [
            item.lower()
            for item in os.environ.get("PATHEXT", ".COM;.EXE").split(os.pathsep)
            if item.lower() in {".com", ".exe"}
        ]
        if requested.suffix.lower() in suffixes:
            suffixes = [""]

    for raw_directory in path_value.split(os.pathsep):
        if not raw_directory:
            continue
        try:
            directory = Path(raw_directory).expanduser().resolve()
        except OSError:
            continue
        if directory == current:
            continue
        for suffix in suffixes:
            candidate = (directory / f"{command}{suffix}").resolve()
            if candidate.is_relative_to(current) or not candidate.is_file():
                continue
            if os.name != "nt" and not os.access(candidate, os.X_OK):
                continue
            return str(candidate)
    raise ExecutableResolutionError(f"Executable was not found on the trusted PATH: {command}")

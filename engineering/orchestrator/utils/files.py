"""Filesystem helpers used by the V0 config loader and doctor.

Deliberately small: only operations with a current consumer live here.
All helpers raise `HarnessPathError` instead of leaking raw `OSError`s.
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.core.exceptions import HarnessPathError


def resolve_path(base: Path, value: str | Path) -> Path:
    """Resolve `value` against `base` unless it is already absolute.

    `~` is expanded. The result is absolute and normalised, but its
    existence is not checked (use `require_directory` / `require_file`).
    """
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def require_directory(path: Path) -> Path:
    """Return `path` if it is an existing directory, else raise."""
    if not path.exists():
        raise HarnessPathError(f"directory does not exist: {path}")
    if not path.is_dir():
        raise HarnessPathError(f"not a directory: {path}")
    return path


def require_file(path: Path) -> Path:
    """Return `path` if it is an existing regular file, else raise."""
    if not path.exists():
        raise HarnessPathError(f"file does not exist: {path}")
    if not path.is_file():
        raise HarnessPathError(f"not a regular file: {path}")
    return path


def read_text(path: Path) -> str:
    """Read a UTF-8 text file, converting OS/encoding errors to `HarnessPathError`."""
    try:
        return require_file(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HarnessPathError(f"cannot read {path}: {exc}") from exc

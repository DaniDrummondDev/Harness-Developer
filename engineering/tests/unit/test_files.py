from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.core.exceptions import HarnessPathError
from orchestrator.utils.files import read_text, require_directory, require_file, resolve_path


def test_resolve_relative_path_against_base(tmp_path: Path) -> None:
    assert resolve_path(tmp_path, "a/../b") == (tmp_path / "b").resolve()


def test_resolve_absolute_path_ignores_base(tmp_path: Path) -> None:
    assert resolve_path(Path("/unused"), tmp_path) == tmp_path.resolve()


def test_require_directory(tmp_path: Path) -> None:
    file = tmp_path / "f.txt"
    file.write_text("x")
    assert require_directory(tmp_path) == tmp_path
    with pytest.raises(HarnessPathError, match="does not exist"):
        require_directory(tmp_path / "missing")
    with pytest.raises(HarnessPathError, match="not a directory"):
        require_directory(file)


def test_require_file(tmp_path: Path) -> None:
    with pytest.raises(HarnessPathError, match="not a regular file"):
        require_file(tmp_path)


def test_read_text(tmp_path: Path) -> None:
    file = tmp_path / "f.txt"
    file.write_text("olá", encoding="utf-8")
    assert read_text(file) == "olá"


def test_read_text_invalid_encoding(tmp_path: Path) -> None:
    file = tmp_path / "bin"
    file.write_bytes(b"\xff\xfe\xfa")
    with pytest.raises(HarnessPathError, match="cannot read"):
        read_text(file)

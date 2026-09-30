"""Shared fixtures.

`harness_root` is an isolated copy of the shipped `config/` inside tmp_path, so
tests exercise the real default configuration (contract) and can mutate it
freely without touching the repository.
"""

from __future__ import annotations

import logging
import shutil
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from orchestrator.config import default_harness_root
from orchestrator.utils.logging import ROOT_LOGGER_NAME

REAL_HARNESS_ROOT = default_harness_root()


@pytest.fixture(autouse=True)
def _reset_orchestrator_logger() -> Iterator[None]:
    """configure_logging mutates a global logger; restore it after each test."""
    logger = logging.getLogger(ROOT_LOGGER_NAME)
    saved = (list(logger.handlers), logger.level, logger.propagate)
    yield
    logger.handlers[:], logger.level, logger.propagate = saved


@pytest.fixture
def harness_root(tmp_path: Path) -> Path:
    root = tmp_path / "harness"
    shutil.copytree(REAL_HARNESS_ROOT / "config", root / "config")
    (root / "templates").mkdir()
    (root / "docs").mkdir()
    # project.yaml ships with `root: ..`, which resolves to tmp_path here.
    return root


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    """An empty but well-formed Global Library (all five type directories)."""
    root = tmp_path / "library"
    for name in ("policies", "guidelines", "rules", "skills", "specialties"):
        (root / name).mkdir(parents=True)
    return root


@pytest.fixture
def write_config(harness_root: Path) -> Callable[[str, str], Path]:
    """Overwrite `config/<name>` with dedented `content`."""

    def _write(name: str, content: str) -> Path:
        path = harness_root / "config" / name
        path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        return path

    return _write

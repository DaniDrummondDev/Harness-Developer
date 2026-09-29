"""Runs `python -m orchestrator` as a real subprocess, from an unrelated cwd."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from orchestrator.utils.shell import run_command


def test_module_help_from_foreign_cwd(tmp_path: Path) -> None:
    result = run_command([sys.executable, "-m", "orchestrator", "--help"], cwd=tmp_path, timeout=60)
    assert result.exit_code == 0, result.stderr
    assert "doctor" in result.stdout


def test_module_doctor_from_foreign_cwd(tmp_path: Path, harness_root: Path) -> None:
    result = run_command(
        [sys.executable, "-m", "orchestrator", "--root", str(harness_root), "doctor"],
        cwd=tmp_path,
        timeout=60,
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Overall" in result.stdout
    assert result.stderr == ""  # no log noise at default level


def test_module_intake_from_foreign_cwd(tmp_path: Path, harness_root: Path) -> None:
    result = run_command(
        [sys.executable, "-m", "orchestrator", "--root", str(harness_root), "intake", "plan V0.2",
         "--intent", "plan"],
        cwd=tmp_path,
        timeout=60,
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)  # stdout is pure JSON
    assert data["state"] == "planned"
    assert data["request"]["mode"] == "interactive"
    assert data["request"]["source"] == "cli"
    assert result.stderr == ""

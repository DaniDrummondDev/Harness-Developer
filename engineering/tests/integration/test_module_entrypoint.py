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


def test_module_library_resolve_from_foreign_cwd(tmp_path: Path, harness_root: Path) -> None:
    # V1: a consumer points --root at its own config/ and inherits the installation's
    # Global Library without any library file under its root.
    assert not any((harness_root / d).exists() for d in ("skills", "policies"))
    result = run_command(
        [sys.executable, "-m", "orchestrator", "--root", str(harness_root), "library", "resolve"],
        cwd=tmp_path,
        timeout=60,
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    keys = [m["key"] for m in data["matches"]]
    assert "skill/python" in keys and "policy/secrets" in keys
    assert result.stderr == ""


def test_module_context_discover_from_foreign_cwd(tmp_path: Path, harness_root: Path) -> None:
    # V1.1: discovery against the fixture project (tmp_path) with the shipped library,
    # run from an unrelated cwd; paths in the result are project-relative.
    docs = harness_root.parent / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("# Notes\n", encoding="utf-8")
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    result = run_command(
        [sys.executable, "-m", "orchestrator", "--root", str(harness_root), "context", "discover",
         "update docs/notes.md"],
        cwd=cwd,
        timeout=60,
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    by_id = {c["id"]: c for c in data["candidates"]}
    assert "policy/secrets" in by_id and "skill/python" in by_id
    assert by_id["doc/docs/notes.md"]["reference"] == {"store": "project", "path": "docs/notes.md"}
    assert {p["discoverer"] for p in by_id["doc/docs/notes.md"]["provenance"]} == {
        "documentation", "repository_hints",
    }
    assert result.stderr == ""


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

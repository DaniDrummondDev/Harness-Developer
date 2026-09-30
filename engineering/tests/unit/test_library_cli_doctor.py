"""V1 Global Library: `library` CLI group and the offline `library` doctor check."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from library_helpers import write_artifact
from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.doctor import CheckStatus, check_library, run_doctor
from orchestrator.library.loader import LIBRARY_ROOT_ENV
from orchestrator.utils.shell import CommandResult

runner = CliRunner()
WriteConfig = Callable[[str, str], Path]


def _git_ok(args: object, *, cwd: Path | None = None, timeout: float | None = None
            ) -> CommandResult:
    return CommandResult(("git",), cwd, 0, "true\n", "", 0.0)


# --- doctor -----------------------------------------------------------------------------


def test_doctor_library_passes_on_shipped_library(harness_root: Path) -> None:
    report = run_doctor(harness_root, environ={}, runner=_git_ok, python_version=(3, 12, 0))
    result = {r.name: r for r in report.results}["library"]
    assert result.status is CheckStatus.PASS
    assert "artifacts at" in result.detail and "skill" in result.detail


def test_doctor_library_fails_on_invalid_library(harness_root: Path, library_root: Path) -> None:
    (library_root / "skills" / "bad.md").write_text("no front matter")
    report = run_doctor(harness_root, environ={}, runner=_git_ok, python_version=(3, 12, 0),
                        library_root=library_root)
    result = {r.name: r for r in report.results}["library"]
    assert result.status is CheckStatus.FAIL
    assert "bad.md" in result.detail and "missing front matter" in result.detail
    assert report.exit_code == 1


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda root: (root / "specialties").rmdir(), "missing 'specialties/'"),
        (lambda root: (root / "skills" / "x.txt").write_text("x"), "unexpected entry"),
        (lambda root: [write_artifact(root, "dup", "rule", filename=f"{n}.md") for n in "ab"],
         "duplicate rule id"),
    ],
)
def test_doctor_library_detects_structure_problems(
    library_root: Path, damage: Callable[[Path], object], message: str
) -> None:
    damage(library_root)
    result = check_library(library_root, {})
    assert result.status is CheckStatus.FAIL
    assert message in result.detail


def test_doctor_library_warns_when_empty(library_root: Path) -> None:
    assert check_library(library_root, {}).status is CheckStatus.WARN


def test_doctor_library_honours_env_root(library_root: Path) -> None:
    write_artifact(library_root, "only", "skill")
    result = check_library(None, {LIBRARY_ROOT_ENV: str(library_root)})
    assert result.status is CheckStatus.PASS
    assert result.detail.startswith("1 artifacts at")


def test_doctor_library_runs_even_without_harness_root(tmp_path: Path) -> None:
    report = run_doctor(tmp_path, environ={}, runner=_git_ok, python_version=(3, 12, 0))
    assert {r.name: r.status for r in report.results}["library"] is CheckStatus.PASS


# --- CLI ----------------------------------------------------------------------------------


def test_library_inspect_lists_shipped_artifacts() -> None:
    result = runner.invoke(app, ["library", "inspect"], env={LIBRARY_ROOT_ENV: ""})
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    keys = [a["key"] for a in data["artifacts"]]
    assert keys[0].startswith("policy/")
    assert "skill/laravel" in keys and "specialty/php-laravel" in keys
    assert all("body" not in a for a in data["artifacts"])


def test_library_inspect_filters_by_type(library_root: Path) -> None:
    write_artifact(library_root, "a", "skill")
    write_artifact(library_root, "b", "policy")
    result = runner.invoke(app, ["library", "inspect", "--type", "skill"],
                           env={LIBRARY_ROOT_ENV: str(library_root)})
    assert result.exit_code == 0, result.output
    assert [a["key"] for a in json.loads(result.stdout)["artifacts"]] == ["skill/a"]


def test_library_inspect_unknown_type_is_usage_error() -> None:
    result = runner.invoke(app, ["library", "inspect", "--type", "agent"])
    assert result.exit_code == 2


def test_library_inspect_invalid_library_exits_1(library_root: Path) -> None:
    (library_root / "rules" / "bad.md").write_text("---\nversion: 9\n---\nx\n")
    result = runner.invoke(app, ["library", "inspect"], env={LIBRARY_ROOT_ENV: str(library_root)})
    assert result.exit_code == 1
    assert "unsupported schema version 9" in result.stderr


def test_library_resolve_uses_project_profile(harness_root: Path, write_config: WriteConfig
                                              ) -> None:
    write_config("project.yaml", """
        version: 1
        project:
          name: shop
          root: ..
          stack: [php, laravel, mysql]
          capabilities: [api]
    """)
    result = runner.invoke(app, ["--root", str(harness_root), "library", "resolve"],
                           env={LIBRARY_ROOT_ENV: ""})
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["profile"] == {"stack": ["laravel", "mysql", "php"], "capabilities": ["api"]}
    matches = {m["key"]: m for m in data["matches"]}
    assert matches["skill/laravel"]["reasons"] == ["stack:laravel"]
    assert matches["skill/api"]["reasons"] == ["capability:api"]
    assert matches["policy/secrets"]["authority"] == "mandatory"
    assert "skill/python" not in matches


def test_library_resolve_with_explicit_profile_needs_no_config(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["--root", str(tmp_path), "library", "resolve", "--stack", "python"],
        env={LIBRARY_ROOT_ENV: ""},
    )
    assert result.exit_code == 0, result.output
    keys = [m["key"] for m in json.loads(result.stdout)["matches"]]
    assert "skill/python" in keys and "skill/laravel" not in keys


def test_library_resolve_rejects_malformed_stack() -> None:
    result = runner.invoke(app, ["library", "resolve", "--stack", "Not Valid"])
    assert result.exit_code == 2


def test_library_resolve_invalid_config_exits_1(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--root", str(tmp_path), "library", "resolve"])
    assert result.exit_code == 1
    assert result.stderr.startswith("error:")

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orchestrator import __version__
from orchestrator.cli import app
from orchestrator.core.request import (
    AdmittedRequest,
    ExecutionMode,
    Intent,
    RequestSource,
    WorkflowState,
)

runner = CliRunner()


def test_root_command_shows_identity_and_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "AI Engineering Harness" in result.stdout
    assert "doctor" in result.stdout


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout
    assert "--root" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_invalid_log_level_is_usage_error() -> None:
    result = runner.invoke(app, ["--log-level", "LOUD", "doctor"])
    assert result.exit_code == 2


def test_unknown_command_is_usage_error() -> None:
    assert runner.invoke(app, ["interactive"]).exit_code == 2


def test_doctor_passes_on_valid_root(harness_root: Path) -> None:
    result = runner.invoke(app, ["--root", str(harness_root), "doctor"])
    assert result.exit_code == 0, result.stdout
    assert "config_valid" in result.stdout
    assert "FAIL" not in result.stdout


def test_doctor_fails_on_invalid_config(harness_root: Path) -> None:
    (harness_root / "config" / "project.yaml").write_text("version: 1\n")
    result = runner.invoke(app, ["--root", str(harness_root), "doctor"])
    assert result.exit_code == 1
    assert "FAIL" in result.stdout


def test_doctor_uses_env_root(harness_root: Path) -> None:
    result = runner.invoke(app, ["doctor"], env={"HARNESS_ROOT": str(harness_root)})
    assert result.exit_code == 0
    assert str(harness_root) in result.stdout.replace("\n", "").replace("│", "").replace(" ", "")


# --- intake (V0.1) ------------------------------------------------------------------


def test_help_lists_intake() -> None:
    assert "intake" in runner.invoke(app, ["--help"]).stdout


def test_intake_prints_admitted_interactive_request(harness_root: Path) -> None:
    result = runner.invoke(
        app,
        ["--root", str(harness_root), "intake", "  add a health endpoint ",
         "--intent", "implement", "--ref", "T-9"],
    )
    assert result.exit_code == 0, result.output

    admitted = AdmittedRequest.model_validate_json(result.stdout)
    assert admitted.state is WorkflowState.PLANNED
    assert admitted.request.mode is ExecutionMode.INTERACTIVE
    assert admitted.request.source is RequestSource.CLI
    assert admitted.request.intent is Intent.IMPLEMENT
    assert admitted.request.instruction == "add a health endpoint"
    assert admitted.request.origin_ref == "T-9"


def test_intake_defaults_to_unclassified_intent(harness_root: Path) -> None:
    result = runner.invoke(app, ["--root", str(harness_root), "intake", "explain the config"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["request"]["intent"] == "unclassified"
    assert data["request"]["origin_ref"] is None


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["intake", "x", "--intent", "deploy"], "intent: unknown value 'deploy'"),
        (["intake", "   "], "instruction"),
    ],
)
def test_intake_rejects_invalid_input(harness_root: Path, args: list[str], expected: str) -> None:
    result = runner.invoke(app, ["--root", str(harness_root), *args])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "error:" in result.stderr
    assert expected in result.stderr


def test_intake_refuses_disabled_interactive_mode(
    harness_root: Path, write_config: Callable[[str, str], Path]
) -> None:
    write_config("modes.yaml", """
        version: 1
        modes:
          interactive: {enabled: false}
          autonomous: {enabled: false}
    """)
    result = runner.invoke(app, ["--root", str(harness_root), "intake", "x"])
    assert result.exit_code == 1
    assert "mode 'interactive' is not enabled" in result.stderr


def test_intake_fails_on_invalid_config(harness_root: Path) -> None:
    (harness_root / "config" / "modes.yaml").write_text("version: 1\n")
    result = runner.invoke(app, ["--root", str(harness_root), "intake", "x"])
    assert result.exit_code == 1
    assert "modes.yaml" in result.stderr


def test_intake_requires_instruction() -> None:
    assert runner.invoke(app, ["intake"]).exit_code == 2

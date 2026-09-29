"""Decisions as seen by operators: `harness decision ...` and the opt-in doctor check."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from jev_emulator import JevEmulator
from typer.testing import CliRunner

from orchestrator.cli import EXIT_FALLBACK_REQUIRED, app
from orchestrator.config import HarnessConfig, load_config
from orchestrator.decisions.service import DecisionService, open_decisions
from orchestrator.doctor import CheckStatus, run_doctor
from orchestrator.utils.shell import CommandResult

WriteConfig = Callable[[str, str], Path]
runner = CliRunner()
ENV = {"JEV_API_KEY": "test-key-not-a-secret"}
JEV_ENABLED = """
    version: 1
    providers:
      jev: {kind: jev, enabled: true}
"""


def _git_ok(
    args: Sequence[str], *, cwd: Path | None = None, timeout: float | None = None
) -> CommandResult:
    return CommandResult(tuple(args), cwd, 0, "true\n", "", 0.0)


@pytest.fixture
def emulator(
    harness_root: Path, write_config: WriteConfig, monkeypatch: pytest.MonkeyPatch
) -> JevEmulator:
    """Jev enabled in config; the CLI's real composition runs against the emulator."""
    write_config("providers.yaml", JEV_ENABLED)
    emulator = JevEmulator()

    def opener(config: HarnessConfig) -> DecisionService:
        return open_decisions(config, ENV, transport=emulator)

    monkeypatch.setattr("orchestrator.cli.open_decisions", opener)
    return emulator


def invoke(root: Path, *args: str) -> tuple[int, Any, str]:
    result = runner.invoke(app, ["--root", str(root), "decision", *args])
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = result.stdout
    return result.exit_code, payload, result.stderr


# --- CLI -----------------------------------------------------------------------------------------


def test_help_lists_decision_commands() -> None:
    result = runner.invoke(app, ["decision", "--help"])
    assert result.exit_code == 0
    for command in ("classify", "route", "severity", "relevance", "health"):
        assert command in result.stdout


def test_classify(harness_root: Path, emulator: JevEmulator) -> None:
    code, outcome, _ = invoke(harness_root, "classify", "Fix failing authentication test")

    assert code == 0
    assert outcome["status"] == "decided"
    assert outcome["kind"] == "classification"
    assert outcome["result"]["choice"] in ("bug", "feature", "refactor")
    assert outcome["result"]["provider"] == "jev"
    assert outcome["result"]["resolved_model"] == "jev-1.13.0"
    assert outcome["telemetry"]["fallback_required"] is False
    question = emulator.last_body["questions"]["decision"]
    assert question["type"] == "choice"
    assert list(question["criteria"]) == ["bug", "feature", "refactor"]


def test_route_with_custom_options(harness_root: Path, emulator: JevEmulator) -> None:
    emulator.pick = "reviewer"
    code, outcome, _ = invoke(
        harness_root, "route", "Review the payment refactor",
        "-o", "architect", "-o", "reviewer", "-q", "Who looks at this first?",
    )
    assert code == 0
    assert (outcome["kind"], outcome["result"]["choice"]) == ("routing", "reviewer")
    question = emulator.last_body["questions"]["decision"]
    assert question["instructions"] == "Who looks at this first?"
    assert list(question["criteria"]) == ["architect", "reviewer"]


def test_severity_is_ordered_and_reports_score(harness_root: Path, emulator: JevEmulator) -> None:
    emulator.pick = "critical"
    code, outcome, _ = invoke(harness_root, "severity", "Checkout is down for every customer")

    assert code == 0
    result = outcome["result"]
    assert (outcome["kind"], result["choice"]) == ("severity", "critical")
    assert 0.0 <= result["score"] <= 1.0
    assert emulator.last_body["questions"]["decision"]["type"] == "score"


def test_relevance_includes_the_task(harness_root: Path, emulator: JevEmulator) -> None:
    code, outcome, _ = invoke(
        harness_root, "relevance", "ADR-007: all money values are integers in cents",
        "--task", "Add a discount field to invoices",
    )
    assert code == 0
    assert outcome["kind"] == "context_relevance"
    assert outcome["result"]["choice"] in ("required", "high_value", "optional", "excluded")
    instructions = emulator.last_body["questions"]["decision"]["instructions"]
    assert instructions.endswith("Task: Add a discount field to invoices")


def test_low_confidence_exits_with_fallback_code(harness_root: Path, emulator: JevEmulator) -> None:
    emulator.peak = 0.5  # 3 options -> confidence 0.25 < 0.70
    code, outcome, _ = invoke(harness_root, "classify", "Something ambiguous")

    assert code == EXIT_FALLBACK_REQUIRED
    assert outcome["status"] == "fallback_required"
    assert outcome["fallback_reason"] == "low_confidence"


def test_unavailable_provider_exits_with_fallback_code(
    harness_root: Path, emulator: JevEmulator
) -> None:
    emulator.down = True
    code, outcome, _ = invoke(harness_root, "classify", "anything")
    assert code == EXIT_FALLBACK_REQUIRED
    assert outcome["fallback_reason"] == "unavailable"


def test_rejected_key_is_an_error(harness_root: Path, emulator: JevEmulator) -> None:
    emulator.fail_status = (401, {"detail": "invalid"})
    code, _, err = invoke(harness_root, "classify", "anything")
    assert code == 1
    assert "credentials rejected (HTTP 401)" in err
    assert ENV["JEV_API_KEY"] not in err


def test_disabled_provider_is_an_error(harness_root: Path) -> None:
    code, _, err = invoke(harness_root, "classify", "anything")  # shipped config: jev disabled
    assert code == 1
    assert "which is disabled" in err


def test_invalid_input_is_an_error(harness_root: Path, emulator: JevEmulator) -> None:
    code, _, err = invoke(harness_root, "classify", "x", "-o", "only-one")
    assert code == 1
    assert "invalid decision request" in err
    assert emulator.calls == []


def test_health(harness_root: Path, emulator: JevEmulator) -> None:
    code, health, _ = invoke(harness_root, "health")
    assert (code, health["status"]) == (0, "healthy")
    emulator.fail_status = (529, {})
    code, health, _ = invoke(harness_root, "health")
    assert (code, health["status"]) == (1, "unavailable")


# --- doctor --------------------------------------------------------------------------------------


def _decisions_check(report: Any) -> Any:
    return next((r for r in report.results if r.name == "decisions"), None)


def test_doctor_skips_decisions_when_provider_disabled(harness_root: Path) -> None:
    report = run_doctor(harness_root, environ={}, runner=_git_ok, python_version=(3, 12, 3))
    assert _decisions_check(report) is None
    assert report.status is CheckStatus.PASS


@pytest.mark.parametrize(
    ("fail_status", "expected"),
    [
        (None, CheckStatus.PASS),
        ((503, {}), CheckStatus.WARN),
        ((401, {}), CheckStatus.FAIL),
    ],
)
def test_doctor_checks_enabled_decisions(
    harness_root: Path, write_config: WriteConfig,
    fail_status: tuple[int, Any] | None, expected: CheckStatus,
) -> None:
    write_config("providers.yaml", JEV_ENABLED)
    emulator = JevEmulator()
    emulator.fail_status = fail_status
    report = run_doctor(
        harness_root, environ=ENV, runner=_git_ok, python_version=(3, 12, 3),
        decision_opener=lambda config: open_decisions(config, ENV, transport=emulator),
    )
    check = _decisions_check(report)
    assert check is not None and check.status is expected
    assert all(path == "/v1/models" for _, path, _ in emulator.calls)  # no inference
    assert ENV["JEV_API_KEY"] not in check.detail


def test_doctor_fails_when_enabled_without_key(
    harness_root: Path, write_config: WriteConfig
) -> None:
    write_config("providers.yaml", JEV_ENABLED)
    report = run_doctor(harness_root, environ={}, runner=_git_ok, python_version=(3, 12, 3))
    check = _decisions_check(report)
    assert check is not None and check.status is CheckStatus.FAIL
    assert "$JEV_API_KEY is not set" in check.detail
    assert load_config(harness_root).providers["jev"].enabled

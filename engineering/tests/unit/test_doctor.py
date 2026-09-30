from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from orchestrator.core.exceptions import CommandNotFoundError
from orchestrator.doctor import (
    CheckResult,
    CheckStatus,
    aggregate,
    check_python_version,
    run_doctor,
)
from orchestrator.utils.shell import CommandResult


class FakeRunner:
    """Stands in for run_command; maps argv[1] to (exit_code, stdout) or an exception."""

    def __init__(self, responses: dict[str, tuple[int, str] | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, args: Sequence[str], *, cwd: Path | None = None, timeout: float | None = None
    ) -> CommandResult:
        self.calls.append(tuple(args))
        response = self.responses[args[1]]
        if isinstance(response, Exception):
            raise response
        code, out = response
        return CommandResult(tuple(args), cwd, code, out, "", 0.0)


GIT_OK = FakeRunner({"--version": (0, "git version 2.43.0\n"), "rev-parse": (0, "true\n")})


def statuses(report_results: Sequence[CheckResult]) -> dict[str, CheckStatus]:
    return {r.name: r.status for r in report_results}


def test_valid_environment_passes(harness_root: Path) -> None:
    runner = FakeRunner({"--version": (0, "git version 2.43.0\n"), "rev-parse": (0, "true\n")})
    report = run_doctor(harness_root, environ={}, runner=runner, python_version=(3, 12, 3))

    assert report.status is CheckStatus.PASS
    assert report.exit_code == 0
    assert set(statuses(report.results)) == {
        "python", "harness_root", "permissions", "config_files",
        "config_valid", "structure", "context", "library", "git", "git_repository",
    }


def test_old_python_fails(harness_root: Path) -> None:
    report = run_doctor(harness_root, environ={}, runner=GIT_OK, python_version=(3, 11, 9))
    assert statuses(report.results)["python"] is CheckStatus.FAIL
    assert report.exit_code == 1


def test_invalid_config_fails(harness_root: Path) -> None:
    (harness_root / "config" / "risks.yaml").write_text("version: 1\nrisks: {}\n")
    report = run_doctor(harness_root, environ={}, runner=GIT_OK, python_version=(3, 12, 0))

    result = {r.name: r for r in report.results}["config_valid"]
    assert result.status is CheckStatus.FAIL
    assert "risks.yaml" in result.detail
    assert report.exit_code == 1
    # git_repository needs a valid config (project root), so it is not run.
    assert "git_repository" not in statuses(report.results)


def test_missing_config_file_fails(harness_root: Path) -> None:
    (harness_root / "config" / "modes.yaml").unlink()
    report = run_doctor(harness_root, environ={}, runner=GIT_OK, python_version=(3, 12, 0))
    assert statuses(report.results)["config_files"] is CheckStatus.FAIL
    assert report.exit_code == 1


def test_missing_harness_root_fails_and_skips_dependent_checks(tmp_path: Path) -> None:
    report = run_doctor(tmp_path, environ={}, runner=GIT_OK, python_version=(3, 12, 0))
    names = statuses(report.results)
    assert names["harness_root"] is CheckStatus.FAIL
    assert "config_valid" not in names
    assert report.exit_code == 1


def test_missing_git_is_warning_not_failure(harness_root: Path) -> None:
    runner = FakeRunner({"--version": CommandNotFoundError("executable not found: git")})
    report = run_doctor(harness_root, environ={}, runner=runner, python_version=(3, 12, 0))

    assert statuses(report.results)["git"] is CheckStatus.WARN
    assert "git_repository" not in statuses(report.results)
    assert report.status is CheckStatus.WARN
    assert report.exit_code == 0


def test_not_a_git_repository_is_warning(harness_root: Path) -> None:
    runner = FakeRunner({"--version": (0, "git version 2\n"), "rev-parse": (128, "")})
    report = run_doctor(harness_root, environ={}, runner=runner, python_version=(3, 12, 0))
    assert statuses(report.results)["git_repository"] is CheckStatus.WARN
    assert ("git", "rev-parse", "--is-inside-work-tree") in runner.calls


def test_missing_optional_directory_is_warning(harness_root: Path) -> None:
    (harness_root / "templates").rmdir()
    report = run_doctor(harness_root, environ={}, runner=GIT_OK, python_version=(3, 12, 0))
    assert statuses(report.results)["structure"] is CheckStatus.WARN
    assert report.exit_code == 0


def test_crashing_check_fails_closed(harness_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_root: Path) -> CheckResult:
        raise RuntimeError("unexpected")

    monkeypatch.setattr("orchestrator.doctor.check_structure", boom)
    report = run_doctor(harness_root, environ={}, runner=GIT_OK, python_version=(3, 12, 0))
    result = {r.name: r for r in report.results}["structure"]
    assert result.status is CheckStatus.FAIL
    assert "check crashed" in result.detail


@pytest.mark.parametrize(
    ("items", "expected", "exit_code"),
    [
        ([CheckStatus.PASS, CheckStatus.PASS], CheckStatus.PASS, 0),
        ([CheckStatus.PASS, CheckStatus.WARN], CheckStatus.WARN, 0),
        ([CheckStatus.WARN, CheckStatus.FAIL, CheckStatus.PASS], CheckStatus.FAIL, 1),
        ([], CheckStatus.FAIL, 1),  # nothing proven -> fail closed
    ],
)
def test_aggregation(items: list[CheckStatus], expected: CheckStatus, exit_code: int) -> None:
    report = aggregate([CheckResult(f"c{i}", s, "") for i, s in enumerate(items)])
    assert report.status is expected
    assert report.exit_code == exit_code


def test_python_version_boundary() -> None:
    assert check_python_version((3, 12, 0)).status is CheckStatus.PASS
    assert check_python_version((3, 13, 1)).status is CheckStatus.PASS
    assert check_python_version((3, 11, 12)).status is CheckStatus.FAIL

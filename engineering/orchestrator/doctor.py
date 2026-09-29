"""`doctor`: deterministic verification of the local environment and V0 foundation.

Each check is a small function returning a `CheckResult` (PASS / WARN / FAIL).
`run_doctor` executes them in a fixed order; checks that depend on an earlier
result (e.g. config validity needs the harness root) are only run when that
prerequisite succeeded. `aggregate` turns the results into a report whose
overall status is the worst individual status.

Severity policy:
- FAIL: the V0 foundation cannot work (wrong Python, missing/invalid config,
  unreadable harness). Exit code 1.
- WARN: something expected by later versions is missing but V0 still works
  (git not installed, project not a git repository, optional folders absent).
- A check that crashes unexpectedly is reported as FAIL (fail closed).

Only technologies actually used in V0 are checked. Providers, Mem0, Jev,
databases or network services are deliberately NOT checked here.

To add a check: write `def check_x(...) -> CheckResult`, call it from
`run_doctor`, and add a test in tests/unit/test_doctor.py.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from orchestrator.config import (
    CONFIG_DIRNAME,
    HarnessConfig,
    load_config,
    missing_config_files,
    resolve_harness_root,
)
from orchestrator.core.exceptions import CommandError, HarnessError
from orchestrator.utils.shell import CommandResult, run_command

MIN_PYTHON = (3, 12)
GIT_TIMEOUT_SECONDS = 10.0
# Folders expected next to config/ but not required for V0 to run.
EXPECTED_DIRECTORIES = ("templates", "docs")


class CheckStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - status label, not a password
    WARN = "WARN"
    FAIL = "FAIL"


_SEVERITY = {CheckStatus.PASS: 0, CheckStatus.WARN: 1, CheckStatus.FAIL: 2}


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    results: tuple[CheckResult, ...]

    @property
    def status(self) -> CheckStatus:
        if not self.results:
            return CheckStatus.FAIL  # nothing proven -> fail closed
        return max((r.status for r in self.results), key=_SEVERITY.__getitem__)

    @property
    def exit_code(self) -> int:
        return 1 if self.status is CheckStatus.FAIL else 0

    def count(self, status: CheckStatus) -> int:
        return sum(1 for r in self.results if r.status is status)


class CommandRunner(Protocol):
    def __call__(
        self, args: Sequence[str], *, cwd: Path | None = ..., timeout: float | None = ...
    ) -> CommandResult: ...


def aggregate(results: Sequence[CheckResult]) -> DoctorReport:
    return DoctorReport(tuple(results))


def _guarded(name: str, check: Callable[[], CheckResult]) -> CheckResult:
    """Run a check, converting unexpected exceptions into FAIL (fail closed)."""
    try:
        return check()
    except Exception as exc:  # noqa: BLE001 - doctor must never crash silently
        return CheckResult(name, CheckStatus.FAIL, f"check crashed: {type(exc).__name__}: {exc}")


# --- individual checks --------------------------------------------------------


def check_python_version(version: tuple[int, int, int]) -> CheckResult:
    found = ".".join(str(part) for part in version)
    required = ".".join(str(part) for part in MIN_PYTHON)
    if version[:2] >= MIN_PYTHON:
        return CheckResult("python", CheckStatus.PASS, f"Python {found} (>= {required})")
    return CheckResult("python", CheckStatus.FAIL, f"Python {found}; {required}+ is required")


def check_harness_root(
    explicit: Path | None, environ: Mapping[str, str] | None
) -> tuple[CheckResult, Path | None]:
    try:
        root = resolve_harness_root(explicit, environ)
    except HarnessError as exc:
        return CheckResult("harness_root", CheckStatus.FAIL, str(exc)), None
    return CheckResult("harness_root", CheckStatus.PASS, str(root)), root


def check_permissions(root: Path) -> CheckResult:
    config_dir = root / CONFIG_DIRNAME
    unreadable = [
        str(path)
        for path in (root, config_dir, *sorted(config_dir.glob("*.yaml")))
        if not os.access(path, os.R_OK)
    ]
    if unreadable:
        detail = "not readable: " + ", ".join(unreadable)
        return CheckResult("permissions", CheckStatus.FAIL, detail)
    return CheckResult("permissions", CheckStatus.PASS, "harness root and config are readable")


def check_config_files(root: Path) -> CheckResult:
    missing = missing_config_files(root)
    if missing:
        return CheckResult("config_files", CheckStatus.FAIL, "missing: " + ", ".join(missing))
    return CheckResult("config_files", CheckStatus.PASS, "all required config files present")


def check_config_valid(root: Path) -> tuple[CheckResult, HarnessConfig | None]:
    try:
        config = load_config(root)
    except HarnessError as exc:
        return CheckResult("config_valid", CheckStatus.FAIL, str(exc)), None
    detail = f"project '{config.project.name}' at {config.project_root}"
    return CheckResult("config_valid", CheckStatus.PASS, detail), config


def check_structure(root: Path) -> CheckResult:
    missing = [name for name in EXPECTED_DIRECTORIES if not (root / name).is_dir()]
    if missing:
        return CheckResult(
            "structure", CheckStatus.WARN, "optional directories missing: " + ", ".join(missing)
        )
    return CheckResult("structure", CheckStatus.PASS, "expected directories present")


def check_git_executable(runner: CommandRunner) -> tuple[CheckResult, bool]:
    try:
        result = runner(["git", "--version"], timeout=GIT_TIMEOUT_SECONDS)
    except CommandError as exc:
        return CheckResult("git", CheckStatus.WARN, f"git unavailable: {exc}"), False
    if not result.ok:
        return CheckResult("git", CheckStatus.WARN, f"git exited {result.exit_code}"), False
    return CheckResult("git", CheckStatus.PASS, result.stdout.strip()), True


def check_git_repository(runner: CommandRunner, project_root: Path) -> CheckResult:
    try:
        result = runner(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project_root,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except CommandError as exc:
        return CheckResult("git_repository", CheckStatus.WARN, f"could not inspect: {exc}")
    if result.ok and result.stdout.strip() == "true":
        return CheckResult("git_repository", CheckStatus.PASS, f"{project_root} is a git work tree")
    return CheckResult(
        "git_repository",
        CheckStatus.WARN,
        f"{project_root} is not a git repository (needed from Git Integration onwards)",
    )


# --- orchestration ------------------------------------------------------------


def run_doctor(
    root: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner = run_command,
    python_version: tuple[int, int, int] | None = None,
) -> DoctorReport:
    """Run all V0 checks. Dependencies are injectable for tests."""
    version = python_version or (
        sys.version_info.major,
        sys.version_info.minor,
        sys.version_info.micro,
    )
    results = [_guarded("python", lambda: check_python_version(version))]

    root_result, harness_root = check_harness_root(root, environ)
    results.append(root_result)

    config: HarnessConfig | None = None
    if harness_root is not None:
        found_root = harness_root
        results.append(_guarded("permissions", lambda: check_permissions(found_root)))
        results.append(_guarded("config_files", lambda: check_config_files(found_root)))
        try:
            config_result, config = check_config_valid(found_root)
        except Exception as exc:  # noqa: BLE001 - fail closed
            config_result = CheckResult("config_valid", CheckStatus.FAIL, f"check crashed: {exc}")
        results.append(config_result)
        results.append(_guarded("structure", lambda: check_structure(found_root)))

    git_result, git_available = check_git_executable(runner)
    results.append(git_result)
    if git_available and config is not None:
        project_root = config.project_root
        results.append(
            _guarded("git_repository", lambda: check_git_repository(runner, project_root))
        )

    return aggregate(results)

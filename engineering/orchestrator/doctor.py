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

Only technologies actually used are checked. Providers, Jev, databases or
network services are deliberately NOT checked here, with two opt-in exceptions:

- `memory` (V0.3) runs only when `memory.enabled: true` in memory.yaml. The
  user opted into Mem0, so doctor asks the backend: HEALTHY -> PASS,
  UNAVAILABLE -> WARN (the Harness still works without memory),
  MISCONFIGURED / missing API key -> FAIL. With memory disabled (the shipped
  default) doctor makes no network call.
- `decisions` (V0.4) runs only when decisions.yaml sets `model` AND that
  model's provider (e.g. jev) is `enabled: true` in providers.yaml. Doctor
  makes an authenticated round trip without inference (Jev: GET /v1/models):
  HEALTHY -> PASS, UNAVAILABLE -> WARN, rejected/missing API key -> FAIL.
  With the provider disabled (the shipped default) no network call is made.

`library` (V1) always runs and is offline: it loads the Global Library (root
from $HARNESS_LIBRARY_ROOT or the installation directory, independent of the
harness root) and FAILs on any structure, parse, schema, duplicate-id or
reference error. An empty but well-formed library is a WARN.

`context` (V1.1) runs when the config is valid and `context.enabled`: it only
validates the configured discovery paths (FAIL if one resolves outside the
project; absent optional paths are listed in the PASS detail). It never runs a
discovery: that needs a request and belongs to `context discover`.

`classification` (V1.2) runs with `context`: it only reports the strategy
`context classify` will use (deterministic rules; decision model when
`classification.probabilistic` and its provider is enabled; OPTIONAL fallback).
WARN when probabilistic classification is requested but decisions.yaml has no
model. It never classifies and never calls the decision provider.

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
from orchestrator.context.discovery import check_discovery_paths
from orchestrator.core.exceptions import CommandError, HarnessError
from orchestrator.decisions.models import HealthStatus as DecisionHealthStatus
from orchestrator.decisions.service import DecisionService, open_decisions
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.loader import resolve_library_root
from orchestrator.library.models import ArtifactType
from orchestrator.memory.models import HealthStatus
from orchestrator.memory.service import MemoryService, open_memory
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


MemoryOpener = Callable[[HarnessConfig], MemoryService]

_MEMORY_STATUS = {
    HealthStatus.HEALTHY: CheckStatus.PASS,
    HealthStatus.UNAVAILABLE: CheckStatus.WARN,
    HealthStatus.MISCONFIGURED: CheckStatus.FAIL,
}


DecisionOpener = Callable[[HarnessConfig], DecisionService]

_DECISION_STATUS = {
    DecisionHealthStatus.HEALTHY: CheckStatus.PASS,
    DecisionHealthStatus.UNAVAILABLE: CheckStatus.WARN,
    DecisionHealthStatus.MISCONFIGURED: CheckStatus.FAIL,
}


def decisions_enabled(config: HarnessConfig) -> bool:
    """True when the user opted into real decisions (model set, provider enabled)."""
    alias = config.decisions.model
    model = config.models.get(alias) if alias is not None else None
    provider = config.providers.get(model.provider) if model is not None else None
    return provider is not None and provider.enabled


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


def check_library(library_root: Path | None, environ: Mapping[str, str] | None) -> CheckResult:
    try:
        library = GlobalLibrary.load(resolve_library_root(library_root, environ))
    except HarnessError as exc:
        return CheckResult("library", CheckStatus.FAIL, str(exc))
    total = len(library.artifacts())
    if total == 0:
        return CheckResult("library", CheckStatus.WARN, f"no artifacts in {library.root}")
    counts = ", ".join(f"{len(library.by_type(t))} {t}" for t in ArtifactType)
    detail = f"{total} artifacts at {library.root} ({counts})"
    return CheckResult("library", CheckStatus.PASS, detail)


def check_context(config: HarnessConfig) -> CheckResult:
    try:
        missing = check_discovery_paths(config)
    except HarnessError as exc:
        return CheckResult("context", CheckStatus.FAIL, str(exc))
    detail = "discovery paths stay inside the project"
    if missing:
        detail += "; optional paths absent: " + ", ".join(missing)
    return CheckResult("context", CheckStatus.PASS, detail)


def check_classification(config: HarnessConfig) -> CheckResult:
    """Structural only: which strategy `context classify` will use. Never opens
    the decision layer (the `decisions` check owns connectivity) and never classifies."""
    settings = config.context.classification
    fallback = "unresolved candidates use the conservative fallback (OPTIONAL)"
    if not settings.probabilistic:
        return CheckResult("classification", CheckStatus.PASS,
                           f"deterministic rules only (probabilistic: false); {fallback}")
    alias = config.decisions.model
    if alias is None or config.decisions.thresholds is None:
        return CheckResult(
            "classification", CheckStatus.WARN,
            f"probabilistic: true but decisions.yaml sets no model; {fallback}",
        )
    if not decisions_enabled(config):
        provider = config.models[alias].provider if alias in config.models else "?"
        return CheckResult(
            "classification", CheckStatus.PASS,
            f"deterministic rules; decision provider '{provider}' is disabled, so {fallback}",
        )
    return CheckResult(
        "classification", CheckStatus.PASS,
        f"deterministic rules, then decision model '{alias}' for unresolved candidates "
        f"(minimum_confidence {config.decisions.thresholds.minimum_confidence:.2f}, "
        f"max_decisions {settings.max_decisions}); otherwise OPTIONAL",
    )


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


def check_memory(config: HarnessConfig, opener: MemoryOpener) -> CheckResult:
    try:
        service = opener(config)
    except HarnessError as exc:  # missing API key, invalid namespace: user must fix config
        return CheckResult("memory", CheckStatus.FAIL, str(exc))
    health = service.health()
    return CheckResult("memory", _MEMORY_STATUS[health.status], f"{health.status}: {health.detail}")


def check_decisions(config: HarnessConfig, opener: DecisionOpener) -> CheckResult:
    try:
        service = opener(config)
    except HarnessError as exc:  # missing API key, no adapter for the kind: fix config
        return CheckResult("decisions", CheckStatus.FAIL, str(exc))
    health = service.health()
    return CheckResult(
        "decisions", _DECISION_STATUS[health.status], f"{health.status}: {health.detail}"
    )


# --- orchestration ------------------------------------------------------------


def run_doctor(
    root: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner = run_command,
    python_version: tuple[int, int, int] | None = None,
    memory_opener: MemoryOpener = open_memory,
    decision_opener: DecisionOpener | None = None,
    library_root: Path | None = None,
) -> DoctorReport:
    """Run all checks. Dependencies are injectable for tests."""
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
        if config is not None and config.memory.enabled:
            loaded = config
            results.append(_guarded("memory", lambda: check_memory(loaded, memory_opener)))
        if config is not None and decisions_enabled(config):
            loaded_cfg = config
            opener: DecisionOpener = decision_opener or (
                lambda cfg: open_decisions(cfg, environ)
            )
            results.append(_guarded("decisions", lambda: check_decisions(loaded_cfg, opener)))
        if config is not None and config.context.enabled:
            context_cfg = config
            results.append(_guarded("context", lambda: check_context(context_cfg)))
            results.append(
                _guarded("classification", lambda: check_classification(context_cfg))
            )

    # Independent of the harness root: the library belongs to the installation.
    results.append(_guarded("library", lambda: check_library(library_root, environ)))

    git_result, git_available = check_git_executable(runner)
    results.append(git_result)
    if git_available and config is not None:
        project_root = config.project_root
        results.append(
            _guarded("git_repository", lambda: check_git_repository(runner, project_root))
        )

    return aggregate(results)

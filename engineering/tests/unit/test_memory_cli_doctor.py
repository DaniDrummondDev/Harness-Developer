"""Memory as seen by operators: `memory.yaml` validation, `harness memory ...`, `doctor`."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.config import HarnessConfig, load_config
from orchestrator.core.exceptions import ConfigValidationError, MemoryConfigurationError
from orchestrator.doctor import CheckResult, CheckStatus, run_doctor
from orchestrator.memory.fake import FakeMemoryProvider
from orchestrator.memory.service import MemoryService
from orchestrator.utils.shell import CommandResult

WriteConfig = Callable[[str, str], Path]
runner = CliRunner()

ENABLED = """
    version: 1
    memory:
      enabled: true
      backend: mem0
      mem0: {base_url: "http://localhost:9"}
"""


def _git_ok(
    args: Sequence[str], *, cwd: Path | None = None, timeout: float | None = None
) -> CommandResult:
    return CommandResult(tuple(args), cwd, 0, "true\n", "", 0.0)


# --- memory.yaml ------------------------------------------------------------------------------


def test_shipped_memory_config_is_declared_but_disabled(harness_root: Path) -> None:
    memory = load_config(harness_root).memory
    assert (memory.enabled, memory.backend) == (False, "mem0")
    assert memory.mem0 is not None and memory.mem0.api_key_env == "MEM0_API_KEY"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("memory: {enabled: true, backend: redis, mem0: {base_url: 'http://x'}}", "backend"),
        ("memory: {enabled: true, backend: mem0}", "mem0 section is missing"),
        ("memory: {enabled: true}", "no memory.backend"),
        ("memory: {backend: mem0, mem0: {base_url: 'ftp://x'}}", "base_url"),
        (
            "memory: {backend: mem0, mem0: {base_url: 'http://x', api_key_env: lower}}",
            "api_key_env",
        ),
        ("memory: {backend: mem0, mem0: {base_url: 'http://x', api_key: sk-123456}}", "api_key"),
        ("memory: {backend: mem0, mem0: {base_url: 'http://x', timeout_seconds: 0}}", "timeout"),
        ("memory: {backend: mem0, mem0: {}}", "base_url"),
        ("memory: {enabled: false, scopes: [project]}", "scopes"),
    ],
)
def test_invalid_memory_config_fails_early(
    harness_root: Path, write_config: WriteConfig, content: str, expected: str
) -> None:
    write_config("memory.yaml", f"version: 1\n{content}\n")
    with pytest.raises(ConfigValidationError, match=expected):
        load_config(harness_root)


# --- CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def fake_backend(
    harness_root: Path, write_config: WriteConfig, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FakeMemoryProvider]:
    """Memory enabled in config, backed by one in-process fake shared by all CLI calls."""
    write_config("memory.yaml", ENABLED)
    provider = FakeMemoryProvider()

    def opener(config: HarnessConfig) -> MemoryService:
        return MemoryService(provider, project=config.project.name)

    monkeypatch.setattr("orchestrator.cli.open_memory", opener)
    yield provider


def invoke(root: Path, *args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["--root", str(root), "memory", *args])
    return result.exit_code, result.stdout, result.stderr


def test_help_lists_memory_commands() -> None:
    result = runner.invoke(app, ["memory", "--help"])
    assert result.exit_code == 0
    for command in ("health", "add", "search", "update", "delete"):
        assert command in result.stdout


def test_cli_crud_round_trip(harness_root: Path, fake_backend: FakeMemoryProvider) -> None:
    code, out, _ = invoke(
        harness_root,
        "add",
        "Deploys run on Tuesdays",
        "--scope",
        "release:v1.0.0",
        "--source",
        "release:v1.0.0",
    )
    assert code == 0
    record = json.loads(out)
    assert record["scope"] == {
        "project": "ai-engineering-harness",
        "kind": "release",
        "key": "v1.0.0",
    }
    assert record["source"] == {"type": "release", "id": "v1.0.0"}

    code, out, _ = invoke(harness_root, "search", "tuesdays deploys", "--scope", "release:v1.0.0")
    assert code == 0 and [h["record"]["id"] for h in json.loads(out)] == [record["id"]]
    code, out, _ = invoke(harness_root, "search", "tuesdays", "--scope", "release:v2.0.0")
    assert code == 0 and json.loads(out) == []

    code, out, _ = invoke(harness_root, "update", record["id"], "Deploys run on Wednesdays")
    assert code == 0 and json.loads(out)["content"] == "Deploys run on Wednesdays"

    assert invoke(harness_root, "delete", record["id"])[:2] == (
        0,
        json.dumps({"deleted": record["id"]}, indent=2) + "\n",
    )
    code, _, err = invoke(harness_root, "delete", record["id"])
    assert code == 1 and "not found" in err


def test_cli_health(harness_root: Path, fake_backend: FakeMemoryProvider) -> None:
    code, out, _ = invoke(harness_root, "health")
    assert code == 0 and json.loads(out)["status"] == "healthy"
    fake_backend.unavailable = True
    code, out, _ = invoke(harness_root, "health")
    assert code == 1 and json.loads(out)["status"] == "unavailable"


def test_cli_blocks_secrets_without_echoing_them(
    harness_root: Path, fake_backend: FakeMemoryProvider
) -> None:
    leaked = "hunter2" + "hunter"
    code, out, err = invoke(
        harness_root,
        "add",
        f"DB_PASSWORD={leaked}",
        "--scope",
        "project",
        "--source",
        "finding:F-1",
    )
    assert (code, out) == (1, "")
    assert "safe ingestion policy" in err and leaked not in err
    assert fake_backend.health().detail == "in-process, 0 memories"


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["add", "x", "--scope", "session:1", "--source", "finding:F"], "unknown scope kind"),
        (["add", "x", "--scope", "project", "--source", "chat:1"], "source 'chat:1'"),
        (["search", "x", "--scope", "task"], "requires a key"),
    ],
)
def test_cli_rejects_invalid_input(
    harness_root: Path, fake_backend: FakeMemoryProvider, args: list[str], expected: str
) -> None:
    code, _, err = invoke(harness_root, *args)
    assert code == 1 and expected in err


def test_cli_refuses_when_memory_disabled(harness_root: Path) -> None:
    code, out, err = invoke(harness_root, "search", "x", "--scope", "project")
    assert (code, out) == (1, "")
    assert "memory is disabled" in err


def test_cli_requires_the_api_key(
    harness_root: Path, write_config: WriteConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config("memory.yaml", ENABLED)
    monkeypatch.delenv("MEM0_API_KEY", raising=False)
    code, _, err = invoke(harness_root, "health")
    assert code == 1 and "$MEM0_API_KEY is not set" in err


# --- doctor -------------------------------------------------------------------------------------


def _doctor(root: Path, opener: Callable[[HarnessConfig], MemoryService]) -> dict[str, CheckResult]:
    report = run_doctor(
        root, environ={}, runner=_git_ok, python_version=(3, 12, 3), memory_opener=opener
    )
    return {r.name: r for r in report.results}


def _never_called(_: HarnessConfig) -> MemoryService:
    raise AssertionError("doctor must not open memory when it is disabled")


def test_doctor_skips_memory_when_disabled(harness_root: Path) -> None:
    assert "memory" not in _doctor(harness_root, _never_called)


@pytest.mark.parametrize(
    ("unavailable", "status"), [(False, CheckStatus.PASS), (True, CheckStatus.WARN)]
)
def test_doctor_reports_memory_health(
    harness_root: Path, write_config: WriteConfig, unavailable: bool, status: CheckStatus
) -> None:
    write_config("memory.yaml", ENABLED)

    def opener(config: HarnessConfig) -> MemoryService:
        return MemoryService(FakeMemoryProvider(unavailable=unavailable), project="demo")

    result = _doctor(harness_root, opener)["memory"]
    assert result.status is status


def test_doctor_fails_on_memory_misconfiguration(
    harness_root: Path, write_config: WriteConfig
) -> None:
    write_config("memory.yaml", ENABLED)

    def opener(config: HarnessConfig) -> MemoryService:
        raise MemoryConfigurationError("$MEM0_API_KEY is not set")

    result = _doctor(harness_root, opener)["memory"]
    assert result.status is CheckStatus.FAIL
    assert "MEM0_API_KEY" in result.detail

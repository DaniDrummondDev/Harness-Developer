"""MemoryService: typed models, reference parsing, policy-before-persistence, composition."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.config import load_config
from orchestrator.core.exceptions import (
    InvalidMemoryInputError,
    MemoryConfigurationError,
    MemoryNotFoundError,
    UnsafeMemoryContentError,
)
from orchestrator.memory.fake import FakeMemoryProvider
from orchestrator.memory.mem0 import Mem0MemoryProvider
from orchestrator.memory.models import (
    MAX_CONTENT_CHARS,
    MemoryScope,
    MemorySource,
    ScopeKind,
    SourceType,
)
from orchestrator.memory.service import MemoryService, open_memory

WriteConfig = Callable[[str, str], Path]
LEAK = "DB_PASSWORD=" + "hunter2hunter"


@pytest.fixture
def fake() -> FakeMemoryProvider:
    return FakeMemoryProvider()


@pytest.fixture
def service(fake: FakeMemoryProvider) -> MemoryService:
    return MemoryService(fake, project="demo")


# --- models -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "key", "namespace"),
    [
        (ScopeKind.PROJECT, None, "demo/project"),
        (ScopeKind.TASK, "T-1", "demo/task/T-1"),
        (ScopeKind.RUN, "2026-09-29.a", "demo/run/2026-09-29.a"),
        (ScopeKind.AGENT, "reviewer", "demo/agent/reviewer"),
        (ScopeKind.RELEASE, "v1.2.0", "demo/release/v1.2.0"),
    ],
)
def test_scope_namespaces(kind: ScopeKind, key: str | None, namespace: str) -> None:
    assert MemoryScope(project="demo", kind=kind, key=key).namespace == namespace


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"kind": "project", "key": "x"}, "takes no key"),
        ({"kind": "task"}, "requires a key"),
        ({"kind": "session", "key": "x"}, "kind"),
        ({"kind": "task", "key": "a/b"}, "pattern"),
        ({"kind": "task", "key": "has space"}, "pattern"),
        ({"kind": "task", "key": "T-1", "extra": 1}, "extra"),
    ],
)
def test_invalid_scope(kwargs: dict[str, object], expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        MemoryScope.model_validate({"project": "demo", **kwargs})


def test_scopes_and_sources_are_immutable() -> None:
    scope = MemoryScope(project="demo", kind=ScopeKind.TASK, key="T-1")
    with pytest.raises(ValidationError, match="frozen"):
        scope.key = "T-2"  # type: ignore[misc]


# --- reference parsing (CLI-friendly form) -----------------------------------------------


def test_parse_scope_refs(service: MemoryService) -> None:
    assert service.scope("project") == MemoryScope(project="demo", kind=ScopeKind.PROJECT)
    assert service.scope(" task:T-1 ") == MemoryScope(
        project="demo", kind=ScopeKind.TASK, key="T-1"
    )


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("session:1", "unknown scope kind 'session'"),
        ("task", "requires a key"),
        ("project:x", "takes no key"),
        ("task:a b", "pattern"),
    ],
)
def test_parse_scope_rejects_invalid(service: MemoryService, ref: str, expected: str) -> None:
    with pytest.raises(InvalidMemoryInputError, match=expected):
        service.scope(ref)


def test_parse_source_refs(service: MemoryService) -> None:
    assert service.source("task_result:T-9") == MemorySource(type=SourceType.TASK_RESULT, id="T-9")
    for bad in ("task_result", "chat:1", "finding:"):
        with pytest.raises(InvalidMemoryInputError, match="source"):
            service.source(bad)


# --- operations ------------------------------------------------------------------------------


def test_add_search_update_delete_through_service(service: MemoryService) -> None:
    scope = service.scope("release:v1.0.0")
    record = service.add(
        "  Release v1.0.0 shipped the provider registry  ",
        scope=scope,
        source=service.source("release:v1.0.0"),
    )
    assert record.content == "Release v1.0.0 shipped the provider registry"  # normalized

    assert [h.record.id for h in service.search("provider registry", scope=scope)] == [record.id]
    assert service.update(record.id, "Release v1.0.0 shipped V0.2").content.endswith("V0.2")
    service.delete(record.id)
    with pytest.raises(MemoryNotFoundError):
        service.delete(record.id)
    assert service.health().ok
    assert service.backend_id == "fake"


def test_unsafe_content_never_reaches_the_provider(
    service: MemoryService, fake: FakeMemoryProvider
) -> None:
    scope, source = service.scope("task:T-1"), service.source("finding:F-1")
    with pytest.raises(UnsafeMemoryContentError):
        service.add(f"Found config:\n{LEAK}", scope=scope, source=source)
    assert fake.health().detail == "in-process, 0 memories"

    record = service.add("safe note", scope=scope, source=source)
    with pytest.raises(UnsafeMemoryContentError):
        service.update(record.id, LEAK)
    assert service.search("safe note", scope=scope)[0].record.content == "safe note"  # unchanged


def test_secret_in_lineage_id_is_blocked(service: MemoryService) -> None:
    source = MemorySource(type=SourceType.FINDING, id="ghp_" + "a1B2" * 9)
    with pytest.raises(UnsafeMemoryContentError, match="github_token"):
        service.add("note", scope=service.scope("project"), source=source)


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.add("   ", scope=s.scope("project"), source=s.source("finding:F")),
        lambda s: s.add(
            "x" * (MAX_CONTENT_CHARS + 1), scope=s.scope("project"), source=s.source("finding:F")
        ),
        lambda s: s.search("", scope=s.scope("project")),
        lambda s: s.search("x", scope=s.scope("project"), limit=0),
        lambda s: s.update(" ", "text"),
        lambda s: s.update("fake-000001", ""),
        lambda s: s.delete(""),
    ],
    ids=["blank", "too-long", "blank-query", "limit-0", "blank-id", "blank-content", "blank-del"],
)
def test_invalid_operations_fail_before_the_backend(
    service: MemoryService, call: Callable[[MemoryService], object]
) -> None:
    with pytest.raises(InvalidMemoryInputError):
        call(service)


def test_project_name_must_be_a_valid_namespace(fake: FakeMemoryProvider) -> None:
    with pytest.raises(MemoryConfigurationError, match="namespace"):
        MemoryService(fake, project="my project")


# --- composition from configuration ------------------------------------------------------------

ENABLED = """
    version: 1
    memory:
      enabled: true
      backend: mem0
      mem0: {base_url: "http://localhost:9", api_key_env: HARNESS_TEST_MEM0_KEY}
"""


def test_open_memory_refuses_when_disabled(harness_root: Path) -> None:
    with pytest.raises(MemoryConfigurationError, match="disabled"):
        open_memory(load_config(harness_root), environ={})


def test_open_memory_requires_the_api_key_env_var(
    harness_root: Path, write_config: WriteConfig
) -> None:
    write_config("memory.yaml", ENABLED)
    with pytest.raises(MemoryConfigurationError, match=r"\$HARNESS_TEST_MEM0_KEY is not set"):
        open_memory(load_config(harness_root), environ={"HARNESS_TEST_MEM0_KEY": "  "})


def test_open_memory_builds_mem0_without_network(
    harness_root: Path, write_config: WriteConfig
) -> None:
    write_config("memory.yaml", ENABLED)
    service = open_memory(load_config(harness_root), environ={"HARNESS_TEST_MEM0_KEY": "k"})
    assert service.backend_id == "mem0"
    assert service.project == "ai-engineering-harness"
    assert isinstance(service._provider, Mem0MemoryProvider)

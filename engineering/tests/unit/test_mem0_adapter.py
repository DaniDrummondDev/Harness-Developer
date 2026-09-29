"""Mem0 adapter boundary: exact wire format, error translation, defensive parsing."""

from __future__ import annotations

import socket
from typing import Any

import pytest
from mem0_emulator import VALID_KEY, Mem0Emulator

from orchestrator.core.exceptions import (
    MemoryConfigurationError,
    MemoryNotFoundError,
    MemoryStoreError,
    MemoryUnavailableError,
)
from orchestrator.memory.mem0 import HEALTH_NAMESPACE, HttpTransport, Mem0MemoryProvider
from orchestrator.memory.models import (
    HealthStatus,
    MemoryQuery,
    MemoryScope,
    MemorySource,
    NewMemory,
    ScopeKind,
    SourceType,
)

SCOPE = MemoryScope(project="demo", kind=ScopeKind.RUN, key="run-7")
SOURCE = MemorySource(type=SourceType.DECISION, id="D-3")
CONTENT = "Chose pgvector over qdrant for self-hosting"


@pytest.fixture
def emulator() -> Mem0Emulator:
    return Mem0Emulator()


@pytest.fixture
def adapter(emulator: Mem0Emulator) -> Mem0MemoryProvider:
    return Mem0MemoryProvider(base_url="http://mem0.test", api_key="unused", transport=emulator)


def test_add_sends_verbatim_content_namespace_and_lineage(
    adapter: Mem0MemoryProvider, emulator: Mem0Emulator
) -> None:
    record = adapter.add(NewMemory(content=CONTENT, scope=SCOPE, source=SOURCE))

    method, path, body = emulator.calls[0]
    assert (method, path) == ("POST", "/memories")
    assert body == {
        "messages": [{"role": "user", "content": CONTENT}],
        "user_id": "demo/run/run-7",
        "metadata": {
            "harness_schema": 1,
            "harness_project": "demo",
            "harness_scope": "run",
            "harness_scope_key": "run-7",
            "harness_source_type": "decision",
            "harness_source_id": "D-3",
        },
        "infer": False,  # no LLM rewriting of Harness memories
    }
    assert emulator.calls[1][:2] == ("GET", f"/memories/{record.id}")  # read back what was stored
    assert record.created_at is not None and record.created_at.tzinfo is not None


def test_project_scope_sends_no_scope_key(
    adapter: Mem0MemoryProvider, emulator: Mem0Emulator
) -> None:
    scope = MemoryScope(project="demo", kind=ScopeKind.PROJECT)
    adapter.add(NewMemory(content=CONTENT, scope=scope, source=SOURCE))
    body = emulator.calls[0][2]
    assert body is not None
    assert body["user_id"] == "demo/project"
    assert "harness_scope_key" not in body["metadata"]


def test_search_filters_by_namespace(adapter: Mem0MemoryProvider, emulator: Mem0Emulator) -> None:
    adapter.search(MemoryQuery(scope=SCOPE, text="pgvector", limit=3))
    assert emulator.calls[-1] == (
        "POST",
        "/search",
        {"query": "pgvector", "filters": {"user_id": "demo/run/run-7"}, "top_k": 3},
    )


def test_search_skips_foreign_or_lineage_less_items(
    adapter: Mem0MemoryProvider, emulator: Mem0Emulator
) -> None:
    kept = adapter.add(NewMemory(content=CONTENT, scope=SCOPE, source=SOURCE))
    # Written by another Mem0 client in the same namespace, without Harness metadata:
    emulator.items["x1"] = {
        "id": "x1",
        "memory": "pgvector legacy",
        "user_id": SCOPE.namespace,
        "metadata": {"role": "user"},
    }
    # Claims our namespace but its metadata says another scope: never returned.
    emulator.items["x2"] = {
        **emulator.items[kept.id],
        "id": "x2",
        "metadata": {**emulator.items[kept.id]["metadata"], "harness_scope_key": "run-8"},
    }
    hits = adapter.search(MemoryQuery(scope=SCOPE, text="pgvector"))
    assert [h.record.id for h in hits] == [kept.id]


def test_health_queries_the_datastore(adapter: Mem0MemoryProvider, emulator: Mem0Emulator) -> None:
    health = adapter.health()
    assert health.status is HealthStatus.HEALTHY
    assert emulator.calls == [("GET", f"/memories?user_id={HEALTH_NAMESPACE}&top_k=1", None)]


@pytest.mark.parametrize(
    ("status", "body", "health", "error"),
    [
        (401, {"detail": "Invalid API key."}, HealthStatus.MISCONFIGURED, MemoryConfigurationError),
        (403, {"detail": "Forbidden"}, HealthStatus.MISCONFIGURED, MemoryConfigurationError),
        (
            502,
            {"detail": "x", "code": "provider_auth_failed"},
            HealthStatus.UNAVAILABLE,
            MemoryUnavailableError,
        ),
        (500, None, HealthStatus.UNAVAILABLE, MemoryUnavailableError),
        (404, {"detail": "Not Found"}, HealthStatus.MISCONFIGURED, MemoryConfigurationError),
        (400, {"detail": "bad"}, HealthStatus.MISCONFIGURED, MemoryStoreError),
    ],
)
def test_http_errors_are_translated(
    adapter: Mem0MemoryProvider,
    emulator: Mem0Emulator,
    status: int,
    body: dict[str, Any] | None,
    health: HealthStatus,
    error: type[MemoryStoreError],
) -> None:
    emulator.fail_status = (status, body)  # type: ignore[assignment]
    assert adapter.health().status is health
    with pytest.raises(error) as excinfo:
        adapter.add(NewMemory(content=CONTENT, scope=SCOPE, source=SOURCE))
    assert CONTENT not in str(excinfo.value)
    if status == 502:
        assert "code=provider_auth_failed" in str(excinfo.value)


def test_rejected_credentials_name_the_env_var_not_the_key(emulator: Mem0Emulator) -> None:
    emulator.api_key = "wrong-key"
    adapter = Mem0MemoryProvider(
        base_url="http://mem0.test",
        api_key="wrong-key",
        api_key_env="MY_MEM0_KEY",
        transport=emulator,
    )
    with pytest.raises(MemoryConfigurationError) as excinfo:
        adapter.search(MemoryQuery(scope=SCOPE, text="x"))
    assert "$MY_MEM0_KEY" in str(excinfo.value)
    assert "wrong-key" not in str(excinfo.value) and VALID_KEY not in str(excinfo.value)


def test_non_uuid_ids_are_not_found_without_a_request(
    adapter: Mem0MemoryProvider, emulator: Mem0Emulator
) -> None:
    with pytest.raises(MemoryNotFoundError):
        adapter.delete("../configure")
    assert emulator.calls == []


def test_unexpected_add_response_is_an_error(
    adapter: Mem0MemoryProvider, emulator: Mem0Emulator
) -> None:
    emulator.fail_status = (200, {"results": []})
    with pytest.raises(MemoryStoreError, match="unexpected add response"):
        adapter.add(NewMemory(content=CONTENT, scope=SCOPE, source=SOURCE))


# --- default HTTP transport ---------------------------------------------------------------


def test_http_transport_rejects_non_http_urls() -> None:
    with pytest.raises(MemoryConfigurationError, match="http"):
        HttpTransport("file:///etc/passwd", "k", timeout=1)


def test_http_transport_connection_refused_is_unavailable() -> None:
    with socket.socket() as probe:  # find a free local port, then close it
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    adapter = Mem0MemoryProvider(base_url=f"http://127.0.0.1:{port}", api_key="k", timeout=2)
    health = adapter.health()
    assert health.status is HealthStatus.UNAVAILABLE
    assert "cannot reach memory backend" in health.detail
    with pytest.raises(MemoryUnavailableError):
        adapter.search(MemoryQuery(scope=SCOPE, text="x"))

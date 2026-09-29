"""MemoryProvider contract suite (V0.3).

`MemoryProviderContract` is reusable: each backend gets a `Test<Backend>`
subclass providing `provider` (healthy, empty) and `unavailable_provider`.
Today: the fake, and the real Mem0 adapter over the offline Mem0 emulator.
The live-server run is tests/integration/test_mem0_persistence.py.
"""

from __future__ import annotations

import pytest
from mem0_emulator import Mem0Emulator

from orchestrator.core.exceptions import (
    MemoryNotFoundError,
    MemoryStoreError,
    MemoryUnavailableError,
)
from orchestrator.memory.base import MemoryProvider
from orchestrator.memory.fake import FakeMemoryProvider
from orchestrator.memory.mem0 import Mem0MemoryProvider
from orchestrator.memory.models import (
    HealthStatus,
    MemoryQuery,
    MemoryScope,
    MemorySource,
    NewMemory,
    ScopeKind,
    SourceType,
)

PROJECT = "demo"
SOURCE = MemorySource(type=SourceType.TASK_RESULT, id="T-1")
SCOPES = [
    MemoryScope(project=PROJECT, kind=ScopeKind.PROJECT),
    MemoryScope(project=PROJECT, kind=ScopeKind.TASK, key="T-1"),
    MemoryScope(project=PROJECT, kind=ScopeKind.RUN, key="run-1"),
    MemoryScope(project=PROJECT, kind=ScopeKind.AGENT, key="reviewer"),
    MemoryScope(project=PROJECT, kind=ScopeKind.RELEASE, key="v1.0.0"),
]
TASK = SCOPES[1]


def new(content: str, scope: MemoryScope = TASK, source: MemorySource = SOURCE) -> NewMemory:
    return NewMemory(content=content, scope=scope, source=source)


def find(provider: MemoryProvider, text: str, scope: MemoryScope = TASK) -> list[str]:
    return [hit.record.id for hit in provider.search(MemoryQuery(scope=scope, text=text))]


class MemoryProviderContract:
    @pytest.fixture
    def provider(self) -> MemoryProvider:
        raise NotImplementedError

    @pytest.fixture
    def unavailable_provider(self) -> MemoryProvider:
        raise NotImplementedError

    def test_satisfies_contract(self, provider: MemoryProvider) -> None:
        assert isinstance(provider, MemoryProvider)
        assert provider.backend_id.strip()

    def test_health(self, provider: MemoryProvider, unavailable_provider: MemoryProvider) -> None:
        assert provider.health().status is HealthStatus.HEALTHY
        health = unavailable_provider.health()  # never raises
        assert health.status is HealthStatus.UNAVAILABLE
        assert not health.ok

    def test_add_round_trips_content_scope_and_lineage(self, provider: MemoryProvider) -> None:
        record = provider.add(new("The build uses uv and pytest"))
        assert record.id
        assert (record.content, record.scope, record.source) == (
            "The build uses uv and pytest",
            TASK,
            SOURCE,
        )

    def test_search_finds_memory_in_its_scope(self, provider: MemoryProvider) -> None:
        record = provider.add(new("Migrations run with alembic before deploy"))
        hits = provider.search(MemoryQuery(scope=TASK, text="alembic migrations"))
        assert [hit.record for hit in hits][:1] == [record]
        assert all(isinstance(hit.score, float) for hit in hits)

    @pytest.mark.parametrize("scope", SCOPES, ids=[s.kind.value for s in SCOPES])
    def test_every_scope_is_supported_and_isolated(
        self, provider: MemoryProvider, scope: MemoryScope
    ) -> None:
        mine = provider.add(new("isolation marker zebra", scope=scope))
        for other in SCOPES:
            if other != scope:
                provider.add(new("isolation marker zebra", scope=other))
        assert [
            hit.record.id for hit in provider.search(MemoryQuery(scope=scope, text="zebra"))
        ] == [mine.id]

    def test_same_kind_different_key_or_project_is_isolated(self, provider: MemoryProvider) -> None:
        provider.add(new("gamma ray note", scope=TASK))
        other_task = MemoryScope(project=PROJECT, kind=ScopeKind.TASK, key="T-2")
        other_project = MemoryScope(project="other", kind=ScopeKind.TASK, key="T-1")
        assert find(provider, "gamma ray", other_task) == []
        assert find(provider, "gamma ray", other_project) == []

    def test_search_respects_limit(self, provider: MemoryProvider) -> None:
        for i in range(4):
            provider.add(new(f"limit check item {i}"))
        assert len(provider.search(MemoryQuery(scope=TASK, text="limit check", limit=2))) == 2

    def test_update_changes_content_and_keeps_identity(self, provider: MemoryProvider) -> None:
        record = provider.add(new("Cache TTL is 60 seconds"))
        updated = provider.update(record.id, "Cache TTL is 300 seconds")
        assert (updated.id, updated.scope, updated.source) == (record.id, TASK, SOURCE)
        assert updated.content == "Cache TTL is 300 seconds"
        hits = provider.search(MemoryQuery(scope=TASK, text="cache TTL 300"))
        assert [h.record.content for h in hits][:1] == ["Cache TTL is 300 seconds"]

    def test_delete_removes_memory(self, provider: MemoryProvider) -> None:
        record = provider.add(new("temporary delete marker"))
        provider.delete(record.id)
        assert record.id not in find(provider, "temporary delete marker")
        with pytest.raises(MemoryNotFoundError):
            provider.delete(record.id)

    @pytest.mark.parametrize(
        "memory_id", ["00000000-0000-0000-0000-000000000001", "not-an-id", "fake-999999"]
    )
    def test_unknown_or_malformed_id_is_not_found(
        self, provider: MemoryProvider, memory_id: str
    ) -> None:
        with pytest.raises(MemoryNotFoundError):
            provider.update(memory_id, "x")
        with pytest.raises(MemoryNotFoundError):
            provider.delete(memory_id)

    def test_unavailable_backend_raises_typed_error(
        self, unavailable_provider: MemoryProvider
    ) -> None:
        with pytest.raises(MemoryUnavailableError) as excinfo:
            unavailable_provider.add(new("private operational note"))
        assert isinstance(excinfo.value, MemoryStoreError)
        assert "private operational note" not in str(excinfo.value)
        with pytest.raises(MemoryUnavailableError):
            unavailable_provider.search(MemoryQuery(scope=TASK, text="x"))


class TestFakeMemoryProvider(MemoryProviderContract):
    @pytest.fixture
    def provider(self) -> MemoryProvider:
        return FakeMemoryProvider()

    @pytest.fixture
    def unavailable_provider(self) -> MemoryProvider:
        return FakeMemoryProvider(unavailable=True)


class TestMem0MemoryProviderOverEmulator(MemoryProviderContract):
    @pytest.fixture
    def provider(self) -> MemoryProvider:
        return Mem0MemoryProvider(
            base_url="http://mem0.test", api_key="unused", transport=Mem0Emulator()
        )

    @pytest.fixture
    def unavailable_provider(self) -> MemoryProvider:
        emulator = Mem0Emulator()
        emulator.down = True
        return Mem0MemoryProvider(base_url="http://mem0.test", api_key="unused", transport=emulator)

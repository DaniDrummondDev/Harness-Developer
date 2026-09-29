"""Deterministic in-process `MemoryProvider` for tests (no network, no Mem0, no secrets).

It implements the Harness contract, not Mem0's internals:

- ids are sequential (`fake-000001`, ...), timestamps come from an injectable clock;
- search is lexical: score = share of distinct query words present in the
  memory; hits with score 0 are dropped; ties keep insertion order;
- scopes are isolated by exact `MemoryScope` equality;
- `unavailable=True` simulates a backend outage: `health()` reports
  UNAVAILABLE and every operation raises `MemoryUnavailableError`;
- state lives in the instance: it does NOT survive a process restart (the
  persistence proof uses the real Mem0 adapter, tests/integration/).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime

from orchestrator.core.exceptions import MemoryNotFoundError, MemoryUnavailableError
from orchestrator.memory.models import (
    HealthStatus,
    MemoryHealth,
    MemoryHit,
    MemoryQuery,
    MemoryRecord,
    NewMemory,
)

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


class FakeMemoryProvider:
    def __init__(
        self, *, unavailable: bool = False, clock: Callable[[], datetime] = _fixed_clock
    ) -> None:
        self.unavailable = unavailable
        self._clock = clock
        self._records: dict[str, MemoryRecord] = {}
        self._next_id = 1

    @property
    def backend_id(self) -> str:
        return "fake"

    def _available(self) -> None:
        if self.unavailable:
            raise MemoryUnavailableError("fake memory backend is unavailable (simulated)")

    def _existing(self, memory_id: str) -> MemoryRecord:
        record = self._records.get(memory_id)
        if record is None:
            raise MemoryNotFoundError(f"memory '{memory_id}' not found")
        return record

    def health(self) -> MemoryHealth:
        if self.unavailable:
            return MemoryHealth(status=HealthStatus.UNAVAILABLE, detail="simulated outage")
        return MemoryHealth(
            status=HealthStatus.HEALTHY, detail=f"in-process, {len(self._records)} memories"
        )

    def add(self, memory: NewMemory) -> MemoryRecord:
        self._available()
        memory_id = f"fake-{self._next_id:06d}"
        self._next_id += 1
        now = self._clock()
        record = MemoryRecord(
            id=memory_id,
            content=memory.content,
            scope=memory.scope,
            source=memory.source,
            created_at=now,
            updated_at=now,
        )
        self._records[memory_id] = record
        return record

    def search(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        self._available()
        wanted = _words(query.text)
        hits = []
        for record in self._records.values():
            if record.scope != query.scope or not wanted:
                continue
            score = len(wanted & _words(record.content)) / len(wanted)
            if score > 0:
                hits.append(MemoryHit(record=record, score=score))
        hits.sort(key=lambda hit: hit.score, reverse=True)  # stable: ties keep insertion order
        return tuple(hits[: query.limit])

    def update(self, memory_id: str, content: str) -> MemoryRecord:
        self._available()
        record = self._existing(memory_id)
        updated = record.model_copy(update={"content": content, "updated_at": self._clock()})
        self._records[memory_id] = updated
        return updated

    def delete(self, memory_id: str) -> None:
        self._available()
        self._existing(memory_id)
        del self._records[memory_id]

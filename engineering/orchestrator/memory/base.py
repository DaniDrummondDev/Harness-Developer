"""`MemoryProvider`: what the Harness needs from a long-term memory backend (V0.3).

    health()                   -> MemoryHealth               (never raises)
    add(NewMemory)             -> MemoryRecord
    search(MemoryQuery)        -> tuple[MemoryHit, ...]      (most relevant first)
    update(memory_id, content) -> MemoryRecord               (scope and lineage unchanged)
    delete(memory_id)          -> None

Separate from `LLMProvider`/`DecisionProvider` (orchestrator/providers/): memory
stores and retrieves context, it does not infer or decide.

Rules every adapter must follow (checked by tests/contract/test_memory_provider_contract.py):

1. `search` returns only memories of exactly `query.scope` (scope isolation);
2. records round-trip `content`, `scope` and `source` unchanged (lineage);
3. `update` changes content only; scope, source and id are preserved;
4. an id that identifies no stored memory — unknown, deleted or malformed —
   raises `MemoryNotFoundError` on `update`/`delete`;
5. `health` reports problems as a status, it never raises;
6. every other failure is a `MemoryStoreError` subclass; backend exceptions
   never escape; error messages never contain memory content or credentials.

Adapters do NOT apply the safe ingestion policy: `MemoryService` does, once,
before any adapter is called (memory/service.py).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from orchestrator.memory.models import MemoryHealth, MemoryHit, MemoryQuery, MemoryRecord, NewMemory


@runtime_checkable
class MemoryProvider(Protocol):
    @property
    def backend_id(self) -> str:
        """Backend name for audit/diagnostics, e.g. "mem0" or "fake"."""
        ...

    def health(self) -> MemoryHealth: ...

    def add(self, memory: NewMemory) -> MemoryRecord: ...

    def search(self, query: MemoryQuery) -> tuple[MemoryHit, ...]: ...

    def update(self, memory_id: str, content: str) -> MemoryRecord: ...

    def delete(self, memory_id: str) -> None: ...

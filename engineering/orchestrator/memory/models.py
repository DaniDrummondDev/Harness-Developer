"""Typed memory contract data (V0.3): scope, lineage, records, queries, health.

Concepts:

- `MemoryScope`   WHERE a memory belongs: always a project, plus one of the
                  roadmap scopes (project, task, run, agent, release) and, except
                  for the project scope itself, the key of that task/run/...
                  Scopes are isolated: a search sees only its exact scope.
- `MemorySource`  WHERE a memory came from (basic lineage, RF-017/RNF-029):
                  the kind of approved artifact and its id, e.g. task_result/T-12.
                  Required: the Harness never stores memory it cannot trace.
- `NewMemory` / `MemoryRecord` / `MemoryQuery` / `MemoryHit` / `MemoryHealth`
                  inputs and outputs of `MemoryProvider` (memory/base.py).

Memory is auxiliary operational context, never a source of truth: nothing
here can express "this memory overrides a doc/ADR/policy/task/Git fact".
Precedence between sources is Context Engineering's job (V1.x).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

# Opaque keys used inside namespaces (project name, task/run/agent/release keys,
# source ids). No whitespace or separators, so namespaces cannot collide.
Key = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
# Upper bound keeps memories small and prevents dumping stdout/files (vision §8).
MAX_CONTENT_CHARS = 8000
Content = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CONTENT_CHARS)
]
MemoryId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScopeKind(StrEnum):
    """Memory scopes named by the roadmap (V0.3)."""

    PROJECT = "project"
    TASK = "task"
    RUN = "run"
    AGENT = "agent"
    RELEASE = "release"


class SourceType(StrEnum):
    """Approved origins of memory (RF-017). There is deliberately no 'free text'
    or 'conversation' type: automatic ingestion is not part of V0.3."""

    TASK_RESULT = "task_result"
    DECISION = "decision"
    FINDING = "finding"
    REMEDIATION = "remediation"
    RELEASE = "release"
    INCIDENT = "incident"
    IMPLEMENTATION_NOTE = "implementation_note"


class MemoryScope(_Model):
    project: Key
    kind: ScopeKind
    key: Key | None = None

    @model_validator(mode="after")
    def _key_matches_kind(self) -> Self:
        if self.kind is ScopeKind.PROJECT and self.key is not None:
            raise ValueError("the project scope takes no key (it is the project itself)")
        if self.kind is not ScopeKind.PROJECT and self.key is None:
            raise ValueError(f"the {self.kind} scope requires a key (e.g. {self.kind}:<id>)")
        return self

    @property
    def namespace(self) -> str:
        """Stable, collision-free identifier of this scope, e.g. `demo/task/T-1`."""
        parts = [self.project, self.kind.value] + ([self.key] if self.key else [])
        return "/".join(parts)

    def __str__(self) -> str:
        return self.kind.value if self.key is None else f"{self.kind.value}:{self.key}"


class MemorySource(_Model):
    type: SourceType
    id: Key

    def __str__(self) -> str:
        return f"{self.type.value}:{self.id}"


class NewMemory(_Model):
    """A memory to persist. Content must already have passed the safe
    ingestion policy (MemoryService enforces this before calling a provider)."""

    content: Content
    scope: MemoryScope
    source: MemorySource


class MemoryRecord(_Model):
    """A stored memory as returned by a provider."""

    id: MemoryId
    content: str
    scope: MemoryScope
    source: MemorySource
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class MemoryQuery(_Model):
    """Search `text` within exactly one scope."""

    scope: MemoryScope
    text: Content
    limit: int = Field(default=5, ge=1, le=50)


class MemoryHit(_Model):
    """A search result. `score` is backend-specific relevance (higher is more
    relevant); compare scores only within one result list."""

    record: MemoryRecord
    score: float


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"  # backend down / unreachable / failing
    MISCONFIGURED = "misconfigured"  # wrong URL, missing or rejected credentials


class MemoryHealth(_Model):
    status: HealthStatus
    detail: str

    @property
    def ok(self) -> bool:
        return self.status is HealthStatus.HEALTHY

"""`MemoryService`: the single entry point the rest of the Harness uses for memory.

    caller (CLI today; Context Engine in V1.x)
        -> MemoryService.add / search / update / delete / health
             1. validate input into typed models      -> InvalidMemoryInputError
             2. safe ingestion policy (add/update)   -> UnsafeMemoryContentError
             3. MemoryProvider (Mem0 adapter or fake)
        <- MemoryRecord / MemoryHit / MemoryHealth

Why a service and not the provider directly: the safety policy and the
project-bound scopes must hold for every backend, so they are enforced here,
once, before any adapter is called. Adapters stay pure translation layers.

`open_memory(config)` is the composition step: `memory.yaml` + environment ->
`Mem0MemoryProvider` -> `MemoryService`. It is the only place that reads the
API key (from the variable named in `memory.mem0.api_key_env`).

Scope and source references use the CLI-friendly form `<kind>[:<key>]`:
`project`, `task:T-12`, `run:2026-09-29-a`, `agent:reviewer`, `release:v1.2.0`;
sources are `<type>:<id>`, e.g. `task_result:T-12`.

No automatic ingestion: nothing in the Harness calls `add` on its own in V0.3.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from orchestrator.config import HarnessConfig
from orchestrator.core.exceptions import InvalidMemoryInputError, MemoryConfigurationError
from orchestrator.memory.base import MemoryProvider
from orchestrator.memory.mem0 import Mem0MemoryProvider
from orchestrator.memory.models import (
    Content,
    MemoryHealth,
    MemoryHit,
    MemoryId,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySource,
    NewMemory,
    ScopeKind,
    SourceType,
)
from orchestrator.memory.safety import ensure_safe

_MEMORY_ID: TypeAdapter[str] = TypeAdapter(MemoryId)
_CONTENT: TypeAdapter[str] = TypeAdapter(Content)


def _problems(exc: PydanticValidationError) -> str:
    # Only locations and messages: pydantic inputs (i.e. content) are never echoed.
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'value'}: {err['msg']}" for err in exc.errors()
    )


class MemoryService:
    def __init__(self, provider: MemoryProvider, *, project: str) -> None:
        try:
            MemoryScope(project=project, kind=ScopeKind.PROJECT)
        except PydanticValidationError as exc:
            raise MemoryConfigurationError(
                f"project name {project!r} cannot be used as a memory namespace: {_problems(exc)}"
            ) from exc
        self._provider = provider
        self.project = project

    @property
    def backend_id(self) -> str:
        return self._provider.backend_id

    # --- parsing of CLI-style references ------------------------------------------------

    def scope(self, ref: str) -> MemoryScope:
        """`project` | `<task|run|agent|release>:<key>` -> scope of this project."""
        kind, _, key = ref.strip().partition(":")
        try:
            return MemoryScope(project=self.project, kind=ScopeKind(kind), key=key or None)
        except ValueError as exc:  # unknown kind (ValueError) or pydantic validation error
            allowed = ", ".join(k.value for k in ScopeKind)
            detail = _problems(exc) if isinstance(exc, PydanticValidationError) else (
                f"unknown scope kind '{kind}' (allowed: {allowed})"
            )
            raise InvalidMemoryInputError(f"scope '{ref}': {detail}") from exc

    @staticmethod
    def source(ref: str) -> MemorySource:
        """`<source_type>:<id>` -> lineage, e.g. `task_result:T-12`."""
        type_, sep, id_ = ref.strip().partition(":")
        try:
            if not sep:
                raise ValueError("expected <type>:<id>")
            return MemorySource(type=SourceType(type_), id=id_)
        except ValueError as exc:
            allowed = ", ".join(t.value for t in SourceType)
            detail = _problems(exc) if isinstance(exc, PydanticValidationError) else str(exc)
            raise InvalidMemoryInputError(
                f"source '{ref}': {detail} (types: {allowed})"
            ) from exc

    # --- operations ----------------------------------------------------------------------

    def health(self) -> MemoryHealth:
        return self._provider.health()

    def add(self, content: str, *, scope: MemoryScope, source: MemorySource) -> MemoryRecord:
        try:
            memory = NewMemory(content=content, scope=scope, source=source)
        except PydanticValidationError as exc:
            raise InvalidMemoryInputError(_problems(exc)) from exc
        ensure_safe(memory.content, memory.source.id)  # before anything leaves the process
        return self._provider.add(memory)

    def search(self, text: str, *, scope: MemoryScope, limit: int = 5) -> tuple[MemoryHit, ...]:
        try:
            query = MemoryQuery(scope=scope, text=text, limit=limit)
        except PydanticValidationError as exc:
            raise InvalidMemoryInputError(_problems(exc)) from exc
        return self._provider.search(query)

    def update(self, memory_id: str, content: str) -> MemoryRecord:
        try:
            memory_id = _MEMORY_ID.validate_python(memory_id)
            content = _CONTENT.validate_python(content)
        except PydanticValidationError as exc:
            raise InvalidMemoryInputError(_problems(exc)) from exc
        ensure_safe(content)
        return self._provider.update(memory_id, content)

    def delete(self, memory_id: str) -> None:
        try:
            memory_id = _MEMORY_ID.validate_python(memory_id)
        except PydanticValidationError as exc:
            raise InvalidMemoryInputError(_problems(exc)) from exc
        self._provider.delete(memory_id)


def open_memory(config: HarnessConfig, environ: Mapping[str, str] | None = None) -> MemoryService:
    """Build the configured memory backend. Raises MemoryConfigurationError when
    memory is disabled or its credentials are missing (fail closed; no network)."""
    section = config.memory
    if not section.enabled:
        raise MemoryConfigurationError(
            "memory is disabled in memory.yaml (set memory.enabled: true to use it)"
        )
    settings = section.mem0
    if section.backend != "mem0" or settings is None:  # guaranteed by config validation
        raise MemoryConfigurationError(f"unsupported memory backend: {section.backend!r}")
    env = os.environ if environ is None else environ
    api_key = env.get(settings.api_key_env, "").strip()
    if not api_key:
        raise MemoryConfigurationError(
            f"${settings.api_key_env} is not set; export the Mem0 API key before using memory"
        )
    provider = Mem0MemoryProvider(
        base_url=settings.base_url,
        api_key=api_key,
        timeout=settings.timeout_seconds,
        api_key_env=settings.api_key_env,
    )
    return MemoryService(provider, project=config.project.name)

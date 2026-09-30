"""`ContextCandidateDiscovery`: runs the discoverers and merges their output (V1.1).

    EngineeringRequest
      -> each discoverer, in a fixed order (library, instructions, adrs,
         documentation, repository_hints, memory)
      -> merge candidates that point at the same resource
      -> sort by kind (policies first ... memory last), then id
      -> ContextDiscoveryResult(request, candidates, sources)

Deduplication: the identity of a *resource* is its canonical location — the
symlink-resolved file for project/library references, the memory id for
memories. The same resource found by several discoverers becomes ONE candidate
with several provenance entries (e.g. `docs/adr/0001.md` is both under a
documentation path and an ADR path; `engineering/policies/secrets.md` is both a
library artifact and a repository file named in the request). The candidate
keeps the kind that comes first in `CandidateKind` (library kinds, then
instructions, adr, doc, source, memory); the other provenance is preserved.
Titles never participate in identity.

`build_discovery(config, library, memory=...)` is the composition step.
Opening memory is left to the caller (CLI), which owns that decision; here
memory is only *searched*, through `MemorySearcher`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from orchestrator.config import HarnessConfig
from orchestrator.context.discoverers import (
    AdrDiscoverer,
    CandidateDiscoverer,
    DocumentationDiscoverer,
    InstructionsDiscoverer,
    LibraryDiscoverer,
    MemoryDiscoverer,
    MemorySearcher,
    RepositoryHintsDiscoverer,
    UnconsultedSource,
)
from orchestrator.context.files import ProjectFiles
from orchestrator.context.models import (
    KIND_ORDER,
    CandidateReference,
    ContextCandidate,
    ContextDiscoveryResult,
    ReferenceStore,
    SourceReport,
    SourceStatus,
)
from orchestrator.core.exceptions import ContextDiscoveryError
from orchestrator.core.request import EngineeringRequest
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.models import ProjectProfile


def _merge(first: ContextCandidate, second: ContextCandidate) -> ContextCandidate:
    winner, other = (first, second) if KIND_ORDER[first.kind] <= KIND_ORDER[second.kind] else (
        second, first
    )
    extra = tuple(p for p in other.provenance if p not in winner.provenance)
    return winner.model_copy(update={"provenance": winner.provenance + extra})


class ContextCandidateDiscovery:
    def __init__(
        self, discoverers: Sequence[CandidateDiscoverer], *, roots: Mapping[ReferenceStore, Path]
    ) -> None:
        names = [d.name for d in discoverers]
        if len(set(names)) != len(names):
            raise ValueError(f"discoverer names must be unique: {names}")
        self._discoverers = tuple(discoverers)
        self._roots = dict(roots)

    def _resource_key(self, reference: CandidateReference) -> str:
        root = self._roots.get(reference.store)
        if root is None:  # memory ids (or a store without a filesystem root)
            return str(reference)
        return str((root / reference.path).resolve())

    def discover(self, request: EngineeringRequest) -> ContextDiscoveryResult:
        merged: dict[str, ContextCandidate] = {}
        reports = []
        for discoverer in self._discoverers:
            found = discoverer.discover(request)
            reports.append(SourceReport(
                discoverer=discoverer.name, status=found.status,
                candidates=len(found.candidates), warnings=found.warnings,
            ))
            for candidate in found.candidates:
                key = self._resource_key(candidate.reference)
                existing = merged.get(key)
                merged[key] = candidate if existing is None else _merge(existing, candidate)
        candidates = sorted(merged.values(), key=lambda c: (KIND_ORDER[c.kind], c.id))
        return ContextDiscoveryResult(
            request=request, candidates=tuple(candidates), sources=tuple(reports)
        )


# --- composition ---------------------------------------------------------------------------


def project_files(config: HarnessConfig) -> ProjectFiles:
    settings = config.context.discovery
    return ProjectFiles(
        config.project_root, exclude_dirs=settings.exclude_dirs,
        max_files=settings.max_files, max_file_bytes=settings.max_file_bytes,
    )


def check_discovery_paths(config: HarnessConfig) -> tuple[str, ...]:
    """Validate every configured discovery path without discovering anything.

    Returns the configured paths that do not exist (optional sources).
    Raises ContextDiscoveryError when one resolves outside the project root.
    """
    files = project_files(config)
    settings = config.context.discovery
    configured = (*settings.instruction_files, *settings.documentation_paths,
                  *settings.adr_paths, *settings.source_roots)
    return tuple(p for p in dict.fromkeys(configured) if not files.configured(p).exists())


def build_discovery(
    config: HarnessConfig,
    library: GlobalLibrary,
    *,
    memory: MemorySearcher | None = None,
    memory_unavailable: str | None = None,
) -> ContextCandidateDiscovery:
    """Compose the discoverers for `config`.

    Memory is consulted only when `memory.enabled` and a searcher is given; when
    enabled but not openable, pass the reason as `memory_unavailable` (reported
    as UNAVAILABLE, discovery continues).

    Raises:
        ContextDiscoveryError: context is disabled, or a configured path escapes
            the project root.
    """
    if not config.context.enabled:
        raise ContextDiscoveryError(
            "context engineering is disabled in context.yaml (set context.enabled: true)"
        )
    check_discovery_paths(config)  # fail fast on unsafe configuration
    settings = config.context.discovery
    files = project_files(config)
    profile = ProjectProfile(
        stack=tuple(config.project.stack), capabilities=tuple(config.project.capabilities)
    )
    discoverers: list[CandidateDiscoverer] = [
        LibraryDiscoverer(library, profile),
        InstructionsDiscoverer(files, settings.instruction_files),
        AdrDiscoverer(files, settings.adr_paths),
        DocumentationDiscoverer(files, settings.documentation_paths),
        RepositoryHintsDiscoverer(files, settings.source_roots),
    ]
    if not config.memory.enabled:
        discoverers.append(UnconsultedSource(
            "memory", SourceStatus.SKIPPED, "memory is disabled in memory.yaml"
        ))
    elif memory is None:
        discoverers.append(UnconsultedSource(
            "memory", SourceStatus.UNAVAILABLE, memory_unavailable or "memory could not be opened"
        ))
    else:
        discoverers.append(MemoryDiscoverer(memory, limit=settings.memory_results))
    roots = {ReferenceStore.PROJECT: files.root, ReferenceStore.LIBRARY: library.root}
    return ContextCandidateDiscovery(discoverers, roots=roots)

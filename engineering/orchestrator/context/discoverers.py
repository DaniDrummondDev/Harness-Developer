"""Candidate discoverers (V1.1): one small class per source that exists today.

    discoverer        source                            kinds
    library           GlobalLibrary.resolve(profile)    policy, guideline, rule, skill, specialty
    instructions      discovery.instruction_files       instructions
    adrs              discovery.adr_paths               adr
    documentation     discovery.documentation_paths     doc
    repository_hints  paths / file names in the request source
    memory            MemorySearcher (MemoryService)    memory

Each discoverer returns `Discovered` (candidates + warnings + status). A source
that is absent, empty or temporarily failing produces warnings, never an
exception; only unsafe configuration raises `ContextDiscoveryError`.

Discoverers only *find*. None of them ranks, classifies, filters by
confidence or calls Jev/an LLM; the library discoverer reuses the library's
own deterministic resolution instead of re-reading artifacts.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from orchestrator.context.files import FoundFile, ProjectFiles
from orchestrator.context.models import (
    CandidateKind,
    CandidateReference,
    ContextCandidate,
    MetadataValue,
    Provenance,
    ReferenceStore,
    SourceStatus,
)
from orchestrator.core.exceptions import MemoryStoreError
from orchestrator.core.request import EngineeringRequest
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.models import ArtifactType, ProjectProfile
from orchestrator.memory.models import MemoryHit, MemoryScope, ScopeKind


@dataclass(frozen=True, slots=True)
class Discovered:
    candidates: tuple[ContextCandidate, ...] = ()
    warnings: tuple[str, ...] = ()
    status: SourceStatus = SourceStatus.OK


class CandidateDiscoverer(Protocol):
    name: str

    def discover(self, request: EngineeringRequest) -> Discovered: ...


def _file_candidate(
    kind: CandidateKind, found: FoundFile, *, title: str, discoverer: str, reason: str,
    metadata: dict[str, MetadataValue] | None = None,
) -> ContextCandidate:
    return ContextCandidate(
        id=f"{kind}/{found.relative}",
        kind=kind,
        title=title,
        reference=CandidateReference(store=ReferenceStore.PROJECT, path=found.relative),
        provenance=(Provenance(discoverer=discoverer, reason=reason),),
        metadata={"size_bytes": found.size, **(metadata or {})},
    )


# --- Global Library ------------------------------------------------------------------------

_KIND_BY_TYPE = {
    ArtifactType.POLICY: CandidateKind.POLICY,
    ArtifactType.GUIDELINE: CandidateKind.GUIDELINE,
    ArtifactType.RULE: CandidateKind.RULE,
    ArtifactType.SKILL: CandidateKind.SKILL,
    ArtifactType.SPECIALTY: CandidateKind.SPECIALTY,
}


class LibraryDiscoverer:
    """Artifacts that apply to the project profile (not to the request text:
    matching knowledge to a task is classification, V1.2)."""

    name = "library"

    def __init__(self, library: GlobalLibrary, profile: ProjectProfile) -> None:
        self._library = library
        self._profile = profile

    def discover(self, request: EngineeringRequest) -> Discovered:
        candidates = []
        for match in self._library.resolve(self._profile):
            artifact = match.artifact
            candidates.append(ContextCandidate(
                id=artifact.key,
                kind=_KIND_BY_TYPE[artifact.type],
                title=artifact.metadata.name,
                reference=CandidateReference(store=ReferenceStore.LIBRARY, path=artifact.source),
                provenance=(Provenance(
                    discoverer=self.name,
                    reason="applies to the project profile: " + ", ".join(match.reasons),
                ),),
                metadata={
                    "authority": str(artifact.authority),
                    "artifact_id": artifact.id,
                    "description": artifact.metadata.description,
                    "tags": artifact.metadata.tags,
                    "applies": match.reasons,
                },
            ))
        return Discovered(tuple(candidates))


# --- configured project files -----------------------------------------------------------------


@dataclass(slots=True)
class _Collected:
    files: list[tuple[FoundFile, str]] = field(default_factory=list)  # (file, configured path)
    warnings: list[str] = field(default_factory=list)


def _collect(files: ProjectFiles, paths: Sequence[str], suffixes: frozenset[str]) -> _Collected:
    """Configured paths: a file is taken as is, a directory is walked; absent -> warning."""
    collected = _Collected()
    for configured in paths:
        path = files.configured(configured)  # fatal if it escapes the project
        if not path.exists():
            collected.warnings.append(f"'{configured}' does not exist")
        elif path.is_dir():
            walked = files.walk(path, suffixes)
            collected.files.extend((found, configured) for found in walked.files)
            collected.warnings.extend(walked.warnings)
        else:
            found, reason = files.check_file(path)
            if found is None:
                collected.warnings.append(f"skipped '{configured}': {reason}")
            else:
                collected.files.append((found, configured))
    return collected


class InstructionsDiscoverer:
    """Agent/project instruction files (CLAUDE.md, AGENTS.md, ...) that exist."""

    name = "instructions"

    def __init__(self, files: ProjectFiles, paths: Sequence[str]) -> None:
        self._files = files
        self._paths = tuple(paths)

    def discover(self, request: EngineeringRequest) -> Discovered:
        collected = _collect(self._files, self._paths, suffixes=frozenset({".md", ".txt"}))
        candidates = tuple(
            _file_candidate(
                CandidateKind.PROJECT_INSTRUCTIONS, found,
                title=ProjectFiles.title(found, ProjectFiles.head(found)),
                discoverer=self.name, reason=f"configured instruction file '{configured}'",
            )
            for found, configured in collected.files
        )
        return Discovered(candidates, tuple(collected.warnings))


DOCUMENTATION_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".txt", ".adoc"})


class DocumentationDiscoverer:
    name = "documentation"

    def __init__(self, files: ProjectFiles, paths: Sequence[str]) -> None:
        self._files = files
        self._paths = tuple(paths)

    def discover(self, request: EngineeringRequest) -> Discovered:
        collected = _collect(self._files, self._paths, DOCUMENTATION_SUFFIXES)
        candidates = tuple(
            _file_candidate(
                CandidateKind.DOCUMENTATION, found,
                title=ProjectFiles.title(found, ProjectFiles.head(found)),
                discoverer=self.name, reason=f"under documentation path '{configured}'",
            )
            for found, configured in collected.files
        )
        return Discovered(candidates, tuple(collected.warnings))


_ADR_INDEX_NAMES = frozenset({"readme.md", "index.md", "template.md"})
_ADR_STATUS = re.compile(r"^\s*[-*]?\s*\**status\**\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_ADR_NUMBER = re.compile(r"^(?:adr-?)?(\d+)", re.IGNORECASE)


class AdrDiscoverer:
    """Every ADR under the configured paths. Relevance to the task is not judged
    here; `status` (e.g. Superseded) is exposed so a later stage can use it."""

    name = "adrs"

    def __init__(self, files: ProjectFiles, paths: Sequence[str]) -> None:
        self._files = files
        self._paths = tuple(paths)

    def discover(self, request: EngineeringRequest) -> Discovered:
        collected = _collect(self._files, self._paths, frozenset({".md", ".markdown"}))
        candidates = []
        for found, configured in collected.files:
            if found.path.name.lower() in _ADR_INDEX_NAMES:
                continue
            head = ProjectFiles.head(found)
            metadata: dict[str, MetadataValue] = {}
            if status := _ADR_STATUS.search(head):
                metadata["status"] = status.group(1)
            if number := _ADR_NUMBER.match(found.path.name):
                metadata["number"] = number.group(1)
            candidates.append(_file_candidate(
                CandidateKind.ADR, found, title=ProjectFiles.title(found, head),
                discoverer=self.name, reason=f"ADR under '{configured}'", metadata=metadata,
            ))
        return Discovered(tuple(candidates), tuple(collected.warnings))


# --- repository hints ------------------------------------------------------------------------

_STRIP = "`'\"()[]{}<>,;!?*"
# A file name: stem of 2+ chars and an extension starting with a letter, so prose
# such as "e.g." or "version 1.2" is not taken for a file.
_EXTENSION = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]+\.[A-Za-z][A-Za-z0-9]{0,9}$")


def extract_hints(text: str) -> tuple[str, ...]:
    """Path-like tokens (`a/b.py`, `docs/`) and file names with an extension
    (`cli.py`), in order of appearance, without duplicates. URLs are ignored and
    `file.py:42` is read as `file.py`."""
    hints: dict[str, None] = {}
    for raw in text.split():
        if "://" in raw:
            continue
        token = raw.strip(_STRIP).split(":", 1)[0].rstrip(".").replace("\\", "/")
        if "/" in token.strip("/") or token.endswith("/") or _EXTENSION.match(token):
            if token.strip("/."):
                hints[token] = None
    return tuple(hints)


class RepositoryHintsDiscoverer:
    """Repository files the request names explicitly — never a scan for relevance.

    A path hint is looked up relative to the project root, then to each source
    root; a directory hint yields its direct files. A bare file name is matched
    exactly against a bounded walk of the source roots. Hints resolving outside
    the project, into excluded directories or to secret files are rejected.
    """

    name = "repository_hints"

    def __init__(self, files: ProjectFiles, source_roots: Sequence[str]) -> None:
        self._files = files
        self._source_roots = tuple(source_roots)

    def discover(self, request: EngineeringRequest) -> Discovered:
        texts = [("request", request.instruction)]
        if request.origin_ref:
            texts.append(("origin_ref", request.origin_ref))
        candidates: list[ContextCandidate] = []
        warnings: list[str] = []
        by_name: dict[str, list[FoundFile]] | None = None
        hints_seen = 0
        for field_name, text in texts:
            for hint in extract_hints(text):
                hints_seen += 1
                reason = f"named in the {field_name}: '{hint}'"
                if "/" in hint:
                    found, warning = self._path_hint(hint)
                else:
                    if by_name is None:
                        by_name, walk_warnings = self._index_names()
                        warnings.extend(walk_warnings)
                    found, warning = by_name.get(hint, []), None
                if warning:
                    warnings.append(warning)
                candidates.extend(
                    _file_candidate(CandidateKind.SOURCE_CODE, f, title=f.relative,
                                    discoverer=self.name, reason=reason)
                    for f in found
                )
        if hints_seen == 0:
            warnings.append("the request names no file or path")
        elif not candidates:
            warnings.append("no repository file matched the request's hints")
        return Discovered(tuple(candidates), tuple(warnings))

    def _bases(self) -> list[Path]:
        roots = [self._files.configured(r) for r in self._source_roots]
        return [self._files.root, *(r for r in roots if r != self._files.root)]

    def _path_hint(self, hint: str) -> tuple[list[FoundFile], str | None]:
        relative = hint.rstrip("/")
        options = [Path(relative)] if Path(relative).is_absolute() else [
            base / relative for base in self._bases()
        ]
        rejected: str | None = None
        for option in options:
            path = Path(os.path.normpath(option))
            reason = self._files.rejection(path)
            if reason is not None:
                rejected = rejected or reason
                continue
            if path.is_dir():
                return self._direct_files(path), None
            found, _ = self._files.check_file(path)
            if found is not None:
                return [found], None
            if path.exists():
                rejected = rejected or "not an acceptable file (size or type)"
        if rejected:
            return [], f"rejected hint '{hint}': {rejected}"
        return [], f"hint '{hint}' not found in the project"

    def _direct_files(self, directory: Path) -> list[FoundFile]:
        found_files = []
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            if entry.name.startswith(".") or entry.is_dir():
                continue
            found, _ = self._files.check_file(entry)
            if found is not None:
                found_files.append(found)
            if len(found_files) >= self._files.max_files:
                break
        return found_files

    def _index_names(self) -> tuple[dict[str, list[FoundFile]], list[str]]:
        index: dict[str, list[FoundFile]] = {}
        warnings: list[str] = []
        for root in self._source_roots:
            path = self._files.configured(root)
            if not path.is_dir():
                warnings.append(f"source root '{root}' is not a directory")
                continue
            walked = self._files.walk(path)
            warnings.extend(w for w in walked.warnings if w.startswith("stopped"))
            for found in walked.files:
                index.setdefault(found.path.name, []).append(found)
        return index, warnings


# --- memory ------------------------------------------------------------------------------------

EXCERPT_CHARS = 280


class MemorySearcher(Protocol):
    """What discovery needs from memory: read-only search (MemoryService fits)."""

    @property
    def project(self) -> str: ...

    def search(
        self, text: str, *, scope: MemoryScope, limit: int = 5
    ) -> tuple[MemoryHit, ...]: ...


class MemoryDiscoverer:
    """Project-scope memories matching the request. A hit becomes a candidate,
    never a selected fact: memory is auxiliary context, not a source of truth."""

    name = "memory"

    def __init__(self, searcher: MemorySearcher, *, limit: int) -> None:
        self._searcher = searcher
        self._limit = limit

    def discover(self, request: EngineeringRequest) -> Discovered:
        scope = MemoryScope(project=self._searcher.project, kind=ScopeKind.PROJECT)
        try:
            hits = self._searcher.search(request.instruction, scope=scope, limit=self._limit)
        except MemoryStoreError as exc:  # unavailable, invalid query...: discovery goes on
            return Discovered(status=SourceStatus.UNAVAILABLE, warnings=(f"search failed: {exc}",))
        candidates = tuple(
            ContextCandidate(
                id=f"memory/{hit.record.id}",
                kind=CandidateKind.MEMORY,
                title=hit.record.content.splitlines()[0][:80],
                reference=CandidateReference(store=ReferenceStore.MEMORY, path=hit.record.id),
                provenance=(Provenance(
                    discoverer=self.name, reason=f"search hit #{rank} in scope '{scope}'"
                ),),
                metadata={
                    "scope": str(hit.record.scope),
                    "lineage": str(hit.record.source),
                    "search_rank": rank,
                    "backend_score": hit.score,
                    "excerpt": hit.record.content[:EXCERPT_CHARS],
                    "source_of_truth": False,
                },
            )
            for rank, hit in enumerate(hits, start=1)
        )
        warnings = () if candidates else ("no memory matched the request",)
        return Discovered(candidates, warnings)


class UnconsultedSource:
    """A source that exists but is not consulted in this run (disabled by
    configuration, or its backend could not be opened). Reported, never faked."""

    def __init__(self, name: str, status: SourceStatus, reason: str) -> None:
        self.name = name
        self._status = status
        self._reason = reason

    def discover(self, request: EngineeringRequest) -> Discovered:
        return Discovered(status=self._status, warnings=(self._reason,))

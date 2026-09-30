"""Context Candidate Discovery contracts (V1.1).

A *candidate* is a source that MAY be relevant to a request. Discovery answers
"what exists that could matter?", never "what is best?" or "what fits in the
prompt?": a candidate carries no classification (REQUIRED/HIGH_VALUE/...), no
relevance score and no budget information — those are V1.2/V1.3.

Candidates are references plus metadata, not content: files are pointed to by
`CandidateReference` (store + relative path) so a later stage can load only what
it selects. The one exception is memory: `MemoryProvider` has no get-by-id, so a
short excerpt of the hit travels with it (memory is small by construction).

The request itself is the *subject* of discovery, not a candidate: it is always
part of the work and is echoed in `ContextDiscoveryResult.request`.

Identity (`ContextCandidate.id`, stable while the source does not change):

    library artifacts   <type>/<id>              policy/secrets, skill/laravel
    project files       <kind>/<project path>    adr/docs/adr/0001-x.md, doc/docs/03-...md
    memory              memory/<memory id>
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.core.request import EngineeringRequest


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidateKind(StrEnum):
    """What a candidate is. Only kinds with a real discoverer exist (V1.1).

    Declaration order is the merge priority (a resource found under two kinds
    keeps the earlier one) and the output order. Library kinds come first and
    follow the library's authority order (policies first).
    """

    POLICY = "policy"
    GUIDELINE = "guideline"
    RULE = "rule"
    SKILL = "skill"
    SPECIALTY = "specialty"
    PROJECT_INSTRUCTIONS = "instructions"
    ADR = "adr"
    DOCUMENTATION = "doc"
    SOURCE_CODE = "source"
    MEMORY = "memory"


KIND_ORDER = {kind: index for index, kind in enumerate(CandidateKind)}


class ReferenceStore(StrEnum):
    """Where a reference points: which root its `path` is relative to."""

    PROJECT = "project"  # project.yaml `root`
    LIBRARY = "library"  # Global Library root (the Harness installation)
    MEMORY = "memory"  # a memory id in the configured memory backend


class CandidateReference(_Model):
    store: ReferenceStore
    path: str = Field(min_length=1)

    def __str__(self) -> str:
        return f"{self.store}:{self.path}"


class Provenance(_Model):
    """Which discoverer found the candidate and why (audit trail)."""

    discoverer: str
    reason: str


# Kind-specific facts for later stages (authority, tags, ADR status, size...).
MetadataValue = str | int | float | bool | tuple[str, ...]


class ContextCandidate(_Model):
    id: str = Field(min_length=1)
    kind: CandidateKind
    title: str
    reference: CandidateReference
    provenance: tuple[Provenance, ...] = Field(min_length=1)
    metadata: dict[str, MetadataValue] = Field(default_factory=dict)


class SourceStatus(StrEnum):
    OK = "ok"  # consulted (possibly with zero candidates)
    SKIPPED = "skipped"  # not consulted by configuration (e.g. memory disabled)
    UNAVAILABLE = "unavailable"  # consulted but failed; discovery continued


class SourceReport(_Model):
    discoverer: str
    status: SourceStatus
    candidates: int = Field(ge=0, description="Found by this discoverer, before merging.")
    warnings: tuple[str, ...] = ()


# Sources named by the architecture that have no real store yet (documented,
# never simulated): task/sprint contracts (V6/V13), Git (V7), previous runs,
# releases and findings (V8+).
UNSUPPORTED_SOURCES = ("task_contract", "sprint", "git", "previous_runs", "releases", "findings")


class ContextDiscoveryResult(_Model):
    request: EngineeringRequest
    candidates: tuple[ContextCandidate, ...]
    sources: tuple[SourceReport, ...]
    unsupported_sources: tuple[str, ...] = UNSUPPORTED_SOURCES

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(f"{s.discoverer}: {w}" for s in self.sources for w in s.warnings)

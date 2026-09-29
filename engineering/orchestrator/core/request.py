"""Engineering request: the single normalized contract the core receives (V0.1).

Every entry point — human-initiated (Interactive Mode) or workflow-initiated
(Autonomous Mode) — is turned into one `EngineeringRequest` by the intake
layer (`orchestrator/intake.py`). The core never sees CLI arguments, MCP
payloads or task files; it only sees this contract.

Concepts (kept separate on purpose):

- `ExecutionMode`  WHO started the work: a human interaction or the workflow itself.
- `RequestSource`  WHERE the request came from (CLI, MCP, a task, ...). It is NOT
                   the provider that will execute it (providers arrive in V0.2).
- `Intent`         WHAT kind of engineering work is asked for. Declared by the
                   caller or `UNCLASSIFIED`; never inferred by an LLM or Jev here.

Invariants enforced by `EngineeringRequest` (see `_check_invariants`):

1. `source` belongs to `mode` (`SOURCES_BY_MODE` partitions sources by mode);
2. `instruction` is not blank;
3. Autonomous requests reference the persisted artifact that originated them
   (`origin_ref`) — the workflow must always be able to say which task/sprint/run
   caused the work (auditability, lineage);
4. Autonomous requests carry a classified intent — the workflow never acts on
   work whose nature it does not know (fail closed, RNF-006);
5. `request_id` is a UUID and `created_at` is timezone-aware (UTC by default).

Enum values are lowercase identifiers so they match `config/*.yaml` keys and
stay stable in serialized form. Renaming a value is a breaking change of
`REQUEST_SCHEMA_VERSION`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

REQUEST_SCHEMA_VERSION: Literal[1] = 1


class ExecutionMode(StrEnum):
    """Operating mode. Both modes share the same contracts and the same core."""

    INTERACTIVE = "interactive"  # started by a human (or a tool acting for one)
    AUTONOMOUS = "autonomous"  # started by the workflow from persisted project state


class RequestSource(StrEnum):
    """Origin of a request (roadmap V0.1). Not the executing provider."""

    # Interactive origins — interfaces, most of which do not exist yet (V14).
    CLI = "cli"
    MCP = "mcp"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    HTTP_API = "http_api"
    # Autonomous origins — persisted workflow artifacts (selection logic: V6/V13).
    ROADMAP = "roadmap"
    SPRINT = "sprint"
    TASK = "task"
    PREVIOUS_RUN = "previous_run"
    PERSISTED_STATE = "persisted_state"


class Intent(StrEnum):
    """Coarse kind of engineering work requested.

    Deliberately small: the docs define no taxonomy yet. Values mirror the
    documented roles/verbs (Architect -> plan, Implementer -> implement,
    Reviewer -> review). Automatic classification belongs to the decision
    layer (V0.4+); until then an unknown intent is stated as UNCLASSIFIED
    instead of guessed.
    """

    PLAN = "plan"
    IMPLEMENT = "implement"
    REVIEW = "review"
    UNCLASSIFIED = "unclassified"


class WorkflowState(StrEnum):
    """Workflow states. V0.1 defines only the initial state; the full state
    machine (transitions, persistence, remaining states) is V6."""

    PLANNED = "planned"


# Each source belongs to exactly one mode. Read-only so it cannot drift at runtime.
SOURCES_BY_MODE: MappingProxyType[ExecutionMode, frozenset[RequestSource]] = MappingProxyType({
    ExecutionMode.INTERACTIVE: frozenset({
        RequestSource.CLI,
        RequestSource.MCP,
        RequestSource.CLAUDE_CODE,
        RequestSource.CODEX,
        RequestSource.HTTP_API,
    }),
    ExecutionMode.AUTONOMOUS: frozenset({
        RequestSource.ROADMAP,
        RequestSource.SPRINT,
        RequestSource.TASK,
        RequestSource.PREVIOUS_RUN,
        RequestSource.PERSISTED_STATE,
    }),
})


def mode_for_source(source: RequestSource) -> ExecutionMode:
    """The only mode a source can belong to."""
    for mode, sources in SOURCES_BY_MODE.items():
        if source in sources:
            return mode
    raise AssertionError(f"source {source!r} is not mapped to a mode")  # guarded by tests


Instruction = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OriginRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EngineeringRequest(BaseModel):
    """A normalized, validated request, independent of where it came from.

    Identity: `request_id` is generated locally (UUID4) when the request is
    created; an existing id is only supplied when rehydrating a serialized
    request. No provider, LLM or memory objects belong here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = REQUEST_SCHEMA_VERSION
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    created_at: AwareDatetime = Field(default_factory=_utc_now)
    mode: ExecutionMode
    source: RequestSource
    intent: Intent = Intent.UNCLASSIFIED
    instruction: Instruction
    origin_ref: OriginRef | None = Field(
        default=None,
        description="Identifier of the originating artifact (task, sprint, run, ...). "
        "Required in Autonomous Mode; optional in Interactive Mode.",
    )

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.source not in SOURCES_BY_MODE[self.mode]:
            raise ValueError(
                f"source '{self.source}' is not valid for mode '{self.mode}' "
                f"(it belongs to mode '{mode_for_source(self.source)}')"
            )
        if self.mode is ExecutionMode.AUTONOMOUS:
            if self.origin_ref is None:
                raise ValueError("autonomous requests require origin_ref")
            if self.intent is Intent.UNCLASSIFIED:
                raise ValueError("autonomous requests require a classified intent")
        return self


class AdmittedRequest(BaseModel):
    """A request accepted by the core, with its initial workflow state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: EngineeringRequest
    state: WorkflowState

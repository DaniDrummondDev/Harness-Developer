"""Global Library contracts (V1).

An *artifact* is one Markdown file with YAML front matter. Its front matter is
`ArtifactMetadata` (schema `version: 1`); its body is the knowledge itself,
kept as plain text and never interpreted or executed.

Five types, semantically distinct (docs/03 §10, §17):

    type        directory      authority     meaning
    policy      policies/      mandatory     non-negotiable rule; nothing below overrides it
    guideline   guidelines/    recommended   convention / expected engineering practice
    rule        rules/         recommended   one concrete, potentially verifiable instruction
    skill       skills/        knowledge     how to do a kind of work well
    specialty   specialties/   knowledge     a knowledge domain (references skills and rules)

`Authority` is derived from the type and cannot be declared by an author, so a
guideline can never claim the force of a policy. Its order is the precedence
used when sorting resolved artifacts (policies first); the full precedence
chain (ADRs, task contract, project guidelines, repository, memory) belongs to
Context Engineering (V1.x).

Roles are not modelled here: a specialty or skill never names a role, provider
or model (unknown keys are rejected).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

# Same shape as config identifiers (project.yaml `stack` entries), so profiles and
# `applies_to` compare by exact string equality.
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$")]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

SCHEMA_VERSION = 1


class ArtifactType(StrEnum):
    # Declaration order = sort order within the same authority.
    POLICY = "policy"
    GUIDELINE = "guideline"
    RULE = "rule"
    SKILL = "skill"
    SPECIALTY = "specialty"


class Authority(StrEnum):
    MANDATORY = "mandatory"
    RECOMMENDED = "recommended"
    KNOWLEDGE = "knowledge"


AUTHORITY_BY_TYPE: Mapping[ArtifactType, Authority] = {
    ArtifactType.POLICY: Authority.MANDATORY,
    ArtifactType.GUIDELINE: Authority.RECOMMENDED,
    ArtifactType.RULE: Authority.RECOMMENDED,
    ArtifactType.SKILL: Authority.KNOWLEDGE,
    ArtifactType.SPECIALTY: Authority.KNOWLEDGE,
}

# Lower rank = higher precedence (docs/03 §17: policies > ... > guidelines > skills).
PRECEDENCE: Mapping[Authority, int] = {
    Authority.MANDATORY: 0,
    Authority.RECOMMENDED: 1,
    Authority.KNOWLEDGE: 2,
}

DIRECTORY_BY_TYPE: Mapping[ArtifactType, str] = {
    ArtifactType.POLICY: "policies",
    ArtifactType.GUIDELINE: "guidelines",
    ArtifactType.RULE: "rules",
    ArtifactType.SKILL: "skills",
    ArtifactType.SPECIALTY: "specialties",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"entries must be unique, got {list(values)}")
    return values


class ProjectProfile(_StrictModel):
    """What a project declares about itself (project.yaml `stack` / `capabilities`).
    Normalized to sorted, de-duplicated tuples so resolution is order-independent."""

    stack: tuple[Slug, ...] = ()
    capabilities: tuple[Slug, ...] = ()

    @field_validator("stack", "capabilities")
    @classmethod
    def _sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class AppliesTo(_StrictModel):
    """When an artifact applies. Exactly one form is allowed:

    - `always: true`                      -> every project;
    - `stacks` and/or `capabilities`      -> projects declaring at least one of them.

    An artifact must declare applicability explicitly; there is no implicit default.
    """

    always: bool = False
    stacks: tuple[Slug, ...] = ()
    capabilities: tuple[Slug, ...] = ()

    _unique_lists = field_validator("stacks", "capabilities")(_unique)

    @model_validator(mode="after")
    def _one_form(self) -> Self:
        conditional = bool(self.stacks or self.capabilities)
        if self.always and conditional:
            raise ValueError("'always: true' cannot be combined with stacks/capabilities")
        if not self.always and not conditional:
            raise ValueError("declare 'always: true' or at least one stack/capability")
        return self

    def reasons(self, profile: ProjectProfile) -> tuple[str, ...]:
        """Why this applies to `profile` (empty = it does not). Exact matches only."""
        if self.always:
            return ("always",)
        return tuple(f"stack:{s}" for s in self.stacks if s in profile.stack) + tuple(
            f"capability:{c}" for c in self.capabilities if c in profile.capabilities
        )


class ArtifactMetadata(_StrictModel):
    """Front matter shared by every artifact type (schema version 1)."""

    version: Literal[1]
    id: Slug
    type: ArtifactType
    name: NonEmptyStr
    description: NonEmptyStr
    tags: tuple[Slug, ...] = ()
    applies_to: AppliesTo

    _unique_tags = field_validator("tags")(_unique)


class SpecialtyMetadata(ArtifactMetadata):
    """A specialty is a knowledge domain; it may reference the skills and rules that
    make it up (RF-004). References are validated when the library is indexed."""

    skills: tuple[Slug, ...] = ()
    rules: tuple[Slug, ...] = ()

    _unique_refs = field_validator("skills", "rules")(_unique)

    def references(self) -> tuple[tuple[ArtifactType, str], ...]:
        return tuple((ArtifactType.SKILL, s) for s in self.skills) + tuple(
            (ArtifactType.RULE, r) for r in self.rules
        )


METADATA_MODEL_BY_TYPE: Mapping[ArtifactType, type[ArtifactMetadata]] = {
    artifact_type: (
        SpecialtyMetadata if artifact_type is ArtifactType.SPECIALTY else ArtifactMetadata
    )
    for artifact_type in ArtifactType
}


@dataclass(frozen=True, slots=True)
class Artifact:
    """A loaded, validated artifact. `source` is its POSIX path relative to the
    library root (for audit output; never used to read anything again)."""

    metadata: ArtifactMetadata
    body: str
    source: str

    @property
    def id(self) -> str:
        return self.metadata.id

    @property
    def type(self) -> ArtifactType:
        return self.metadata.type

    @property
    def key(self) -> str:
        """Library-wide unique identity: ids are unique per type (`skill/testing`
        and `guideline/testing` are different artifacts)."""
        return f"{self.type}/{self.id}"

    @property
    def authority(self) -> Authority:
        return AUTHORITY_BY_TYPE[self.type]

    def summary(self) -> dict[str, object]:
        """JSON-ready metadata for inspection (the body is left out)."""
        return {
            "key": self.key,
            "authority": str(self.authority),
            "source": self.source,
            **self.metadata.model_dump(mode="json"),
        }


@dataclass(frozen=True, slots=True)
class Match:
    """One artifact that applies to a project profile, with the exact reasons."""

    artifact: Artifact
    reasons: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        return {**self.artifact.summary(), "reasons": list(self.reasons)}

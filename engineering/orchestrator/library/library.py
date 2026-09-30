"""`GlobalLibrary`: indexed, validated, read-only view of one library root (V1).

    GlobalLibrary.load(root)        load_artifacts() -> index -> cross-checks
    library.artifacts()             every artifact, in precedence order
    library.by_type(type)           one type, sorted by id
    library.get(type, id)           one artifact (ArtifactNotFoundError)
    library.resolve(profile)        artifacts applicable to a project profile

Resolution is deliberately simple and deterministic: an artifact applies when
its `applies_to` is `always`, or names a stack/capability the profile declares
(exact string match; no aliases, no semantics, no Jev, no LLM). Results are
ordered by authority (policies first), then type, then id, and each carries the
reasons it matched. Selecting *which* applicable knowledge enters a prompt
(classification, scoring, budget) is Context Engineering (V1.1+).

The class has no knowledge of CLI, config files, providers or memory: it is
given a root and returns typed values.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from orchestrator.core.exceptions import ArtifactNotFoundError, ArtifactValidationError
from orchestrator.library.loader import load_artifacts
from orchestrator.library.models import (
    PRECEDENCE,
    Artifact,
    ArtifactType,
    Match,
    ProjectProfile,
    SpecialtyMetadata,
)

_TYPE_ORDER = {artifact_type: index for index, artifact_type in enumerate(ArtifactType)}


def _precedence_key(artifact: Artifact) -> tuple[int, int, str]:
    return (PRECEDENCE[artifact.authority], _TYPE_ORDER[artifact.type], artifact.id)


class GlobalLibrary:
    def __init__(self, root: Path, artifacts: Iterable[Artifact]) -> None:
        """Index `artifacts` (loaded from `root`) and check cross-artifact invariants.

        Raises:
            ArtifactValidationError: duplicate id within a type, or a reference to
                an artifact that does not exist.
        """
        self._root = root
        index: dict[tuple[ArtifactType, str], Artifact] = {}
        for artifact in artifacts:
            key = (artifact.type, artifact.id)
            if key in index:
                raise ArtifactValidationError(
                    f"duplicate {artifact.type} id '{artifact.id}' "
                    f"(already declared in {index[key].source})",
                    path=root / artifact.source,
                )
            index[key] = artifact
        self._index = index
        self._ordered = tuple(sorted(index.values(), key=_precedence_key))
        self._check_references()

    @classmethod
    def load(cls, root: Path) -> GlobalLibrary:
        """Load and validate the library under `root` (see library/loader.py)."""
        resolved = root.expanduser().resolve()
        return cls(resolved, load_artifacts(resolved))

    def _check_references(self) -> None:
        for artifact in self._ordered:
            if not isinstance(artifact.metadata, SpecialtyMetadata):
                continue
            for ref_type, ref_id in artifact.metadata.references():
                if (ref_type, ref_id) not in self._index:
                    raise ArtifactValidationError(
                        f"references unknown {ref_type} '{ref_id}'",
                        path=self._root / artifact.source,
                    )

    @property
    def root(self) -> Path:
        return self._root

    def artifacts(self) -> tuple[Artifact, ...]:
        """Every artifact: authority (policies first), then type, then id."""
        return self._ordered

    def by_type(self, artifact_type: ArtifactType) -> tuple[Artifact, ...]:
        return tuple(a for a in self._ordered if a.type is artifact_type)

    def get(self, artifact_type: ArtifactType, artifact_id: str) -> Artifact:
        try:
            return self._index[(artifact_type, artifact_id)]
        except KeyError:
            raise ArtifactNotFoundError(
                f"no {artifact_type} with id '{artifact_id}'", path=self._root
            ) from None

    def resolve(self, profile: ProjectProfile) -> tuple[Match, ...]:
        """Artifacts applicable to `profile`, in precedence order, with reasons."""
        matches = []
        for artifact in self._ordered:
            reasons = artifact.metadata.applies_to.reasons(profile)
            if reasons:
                matches.append(Match(artifact=artifact, reasons=reasons))
        return tuple(matches)

"""Builders for V1.2 Context Classification tests (offline: no Jev, no network)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from orchestrator.config import DecisionThresholds
from orchestrator.context.models import (
    CandidateKind,
    CandidateReference,
    ContextCandidate,
    MetadataValue,
    Provenance,
    ReferenceMatch,
    ReferenceStore,
)
from orchestrator.core.request import EngineeringRequest
from orchestrator.decisions.service import DecisionService
from orchestrator.intake import normalize_request
from orchestrator.providers.base import DecisionProvider, DecisionRequest, DecisionResult
from orchestrator.providers.resolution import ResolvedModel

MODEL = ResolvedModel(alias="decision", provider="scripted", model_id="judge-v1")
LIBRARY_KINDS = {
    CandidateKind.POLICY, CandidateKind.GUIDELINE, CandidateKind.RULE, CandidateKind.SKILL,
    CandidateKind.SPECIALTY,
}


def request(text: str = "fix the invoice rounding", ref: str | None = None) -> EngineeringRequest:
    return normalize_request(source="cli", instruction=text, origin_ref=ref)


def candidate(
    kind: CandidateKind,
    path: str,
    *,
    discoverer: str = "test",
    match: ReferenceMatch | None = None,
    metadata: Mapping[str, MetadataValue] | None = None,
    extra: tuple[Provenance, ...] = (),
) -> ContextCandidate:
    """A candidate as discovery would produce it (library kinds: `path` is the artifact id)."""
    if kind in LIBRARY_KINDS:
        cid, reference = f"{kind}/{path}", CandidateReference(
            store=ReferenceStore.LIBRARY, path=f"{kind}s/{path}.md"
        )
    elif kind is CandidateKind.MEMORY:
        cid = f"memory/{path}"
        reference = CandidateReference(store=ReferenceStore.MEMORY, path=path)
    else:
        cid = f"{kind}/{path}"
        reference = CandidateReference(store=ReferenceStore.PROJECT, path=path)
    return ContextCandidate(
        id=cid, kind=kind, title=path, reference=reference,
        provenance=(Provenance(discoverer=discoverer, reason=f"via {discoverer}", match=match),
                    *extra),
        metadata=dict(metadata or {}),
    )


def library(kind: CandidateKind, artifact_id: str, authority: str, *applies: str,
            match: ReferenceMatch | None = None) -> ContextCandidate:
    extra = () if match is None else (Provenance(
        discoverer="repository_hints", reason="named in the request", match=match),)
    return candidate(kind, artifact_id, discoverer="library", extra=extra, metadata={
        "authority": authority, "artifact_id": artifact_id,
        "description": f"About {artifact_id}.", "tags": (), "applies": applies or ("always",),
    })


class ScriptedDecisionProvider:
    """A DecisionProvider whose answer depends on the subject: the first key of
    `answers` found in the subject decides (choice, confidence); else `default`."""

    provider_id = "scripted"

    def __init__(self, answers: Mapping[str, tuple[str, float]] | None = None,
                 default: tuple[str, float] = ("OPTIONAL", 0.9)) -> None:
        self._answers = dict(answers or {})
        self._default = default
        self.requests: list[DecisionRequest] = []

    def decide(self, request: DecisionRequest) -> DecisionResult:
        self.requests.append(request)
        subject = request.subject or ""
        choice, confidence = next(
            (answer for key, answer in self._answers.items() if key in subject), self._default
        )
        score = request.options.index(choice) / (len(request.options) - 1) if (
            request.ordered and choice in request.options) else None
        return DecisionResult(provider=self.provider_id, model=request.model, choice=choice,
                              confidence=confidence, kind=request.kind, score=score)


def decision_service(provider: DecisionProvider, minimum: float = 0.7) -> DecisionService:
    """The real decision layer (boundary validation + threshold) over a test adapter."""
    return DecisionService(
        provider,
        model=MODEL, thresholds=DecisionThresholds(minimum_confidence=minimum),
        clock=lambda: 0.0, now=lambda: datetime(2026, 9, 30, tzinfo=UTC),
    )

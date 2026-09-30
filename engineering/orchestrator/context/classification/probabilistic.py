"""Probabilistic classification (V1.2): the decision layer for candidates no
deterministic rule resolved.

The classifier depends on `Decider`, a Protocol that `DecisionService` (V0.4)
satisfies; it never sees a vendor SDK, an HTTP client or an API key. The
DecisionService already validates the provider's answer (choice in options,
identity echoed) and applies decisions.yaml `thresholds.minimum_confidence`,
so this module only maps its outcome:

    outcome                                   classification
    DECIDED, choice in EXCLUDED/OPTIONAL/      PROBABILISTIC, that class, confidence,
      HIGH_VALUE                                 relevance (= ordered score), provider
    FALLBACK_REQUIRED low_confidence          FALLBACK OPTIONAL, suggestion = the choice
    FALLBACK_REQUIRED invalid_response        FALLBACK OPTIONAL + warning
    FALLBACK_REQUIRED unavailable / timeout   FALLBACK OPTIONAL + warning; the provider
                                                is not consulted again in this run
    raised ProviderError (credentials, 422)   same as unavailable (never hidden)
    DECIDED with a choice outside the options FALLBACK OPTIONAL + warning (defence in
      (a Decider that breaks the contract)      depth: REQUIRED can never come from here)

One decision per candidate: `DecisionProvider` answers one question per call
(no batch contract exists), which also keeps each decision individually
auditable. `max_decisions` bounds the calls of one run.

Input minimisation: the subject holds the request (truncated), the candidate's
kind, title, reference, provenance reasons and an allowlist of metadata
(description, tags, applies, status, lineage, excerpt). No file content is read
and nothing else is sent. A subject that the memory safety policy would block
(secret-looking text) is never sent: the candidate falls back instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from orchestrator.context.classification.models import (
    FALLBACK_CLASS,
    PROBABILISTIC_CLASSES,
    ContextClass,
    ContextClassification,
    Evidence,
    SelectedBy,
)
from orchestrator.context.models import ContextCandidate
from orchestrator.core.exceptions import ProviderError
from orchestrator.core.request import EngineeringRequest
from orchestrator.decisions.models import DecisionOutcome, DecisionStatus, FallbackReason
from orchestrator.memory.safety import evaluate
from orchestrator.providers.base import DecisionKind

QUESTION = (
    "How valuable is this context candidate for carrying out the engineering request "
    "described in the subject?"
)
OPTIONS = tuple(str(cls) for cls in PROBABILISTIC_CLASSES)  # ordered: lowest value first
DESCRIPTIONS = {
    ContextClass.EXCLUDED.value: "Unrelated to the request, not applicable, or outdated.",
    ContextClass.OPTIONAL.value: "Possibly useful, but the work does not depend on it.",
    ContextClass.HIGH_VALUE.value: "Strongly related to the request; likely to improve the work.",
}
REQUEST_CHARS = 600
SAFE_METADATA = ("description", "tags", "applies", "status", "lineage", "excerpt")


class Decider(Protocol):
    """What classification needs from the decision layer (DecisionService fits)."""

    @property
    def provider_id(self) -> str: ...

    def decide(
        self,
        *,
        question: str,
        options: tuple[str, ...] | list[str],
        kind: DecisionKind = ...,
        subject: str | None = None,
        ordered: bool = False,
        descriptions: Mapping[str, str] | None = None,
    ) -> DecisionOutcome: ...


def decision_subject(request: EngineeringRequest, candidate: ContextCandidate) -> str:
    """The minimal, content-free description of one candidate sent to the decider."""
    instruction = request.instruction
    if len(instruction) > REQUEST_CHARS:
        instruction = instruction[:REQUEST_CHARS] + "..."
    lines = [
        f"Request (intent: {request.intent}): {instruction}",
        f"Candidate kind: {candidate.kind}",
        f"Title: {candidate.title}",
        f"Reference: {candidate.reference}",
        *(f"Found by {p.discoverer}: {p.reason}" for p in candidate.provenance),
    ]
    for key in SAFE_METADATA:
        value = candidate.metadata.get(key)
        if value is None or value == "" or value == ():
            continue
        text = ", ".join(value) if isinstance(value, tuple) else str(value)
        lines.append(f"{key.capitalize()}: {text}")
    return "\n".join(lines)


@dataclass(slots=True)
class _Run:
    """State of one classification run (never shared between runs)."""

    calls: int = 0
    stopped: str | None = None  # why the provider is no longer consulted
    not_consulted: int = 0  # candidates skipped because the provider stopped
    over_limit: int = 0  # candidates skipped because max_decisions was reached
    warnings: list[str] = field(default_factory=list)


class ProbabilisticClassifier:
    def __init__(self, decider: Decider, *, max_decisions: int) -> None:
        if max_decisions < 1:
            raise ValueError("max_decisions must be >= 1")
        self._decider = decider
        self._max_decisions = max_decisions

    @property
    def provider_id(self) -> str:
        return self._decider.provider_id

    def classify(
        self, request: EngineeringRequest, candidates: Sequence[ContextCandidate]
    ) -> tuple[tuple[ContextClassification, ...], tuple[str, ...]]:
        """One classification per candidate (same order) plus run warnings."""
        run = _Run()
        results = tuple(self._classify_one(request, candidate, run) for candidate in candidates)
        if run.over_limit:
            run.warnings.append(
                f"max_decisions ({self._max_decisions}) reached: {run.over_limit} candidate(s) "
                f"use the conservative fallback ({FALLBACK_CLASS})"
            )
        if run.not_consulted:
            run.warnings.append(
                f"{run.not_consulted} further candidate(s) were not sent to "
                f"'{self.provider_id}' and use the conservative fallback ({FALLBACK_CLASS})"
            )
        return results, tuple(run.warnings)

    def _classify_one(self, request: EngineeringRequest, candidate: ContextCandidate,
                      run: _Run) -> ContextClassification:
        if run.stopped is not None:
            run.not_consulted += 1
            return ContextClassification.fallback(
                Evidence.DECISION_UNAVAILABLE, f"not consulted: {run.stopped}"
            )
        if run.calls >= self._max_decisions:
            run.over_limit += 1
            return ContextClassification.fallback(
                Evidence.DECISION_LIMIT_REACHED,
                f"decision limit reached ({self._max_decisions} calls in this run)",
            )
        subject = decision_subject(request, candidate)
        safety = evaluate(subject)
        if not safety.allowed:
            run.warnings.append(
                f"{candidate.id}: decision input withheld (matched: {', '.join(safety.rules)})"
            )
            return ContextClassification.fallback(
                Evidence.UNSAFE_DECISION_INPUT,
                "decision input looked sensitive and was not sent: " + ", ".join(safety.rules),
            )
        run.calls += 1
        try:
            outcome = self._decider.decide(
                question=QUESTION, options=OPTIONS, kind=DecisionKind.CONTEXT_RELEVANCE,
                subject=subject, ordered=True, descriptions=DESCRIPTIONS,
            )
        except ProviderError as exc:
            run.stopped = f"decision provider '{self.provider_id}' failed: {exc}"
            run.warnings.append(run.stopped)
            return ContextClassification.fallback(Evidence.DECISION_UNAVAILABLE, run.stopped)
        return self._from_outcome(candidate, outcome, run)

    def _from_outcome(self, candidate: ContextCandidate, outcome: DecisionOutcome,
                      run: _Run) -> ContextClassification:
        result = outcome.result
        provider = result.provider if result else self.provider_id
        model = (result.resolved_model or result.model) if result else None
        if outcome.status is DecisionStatus.DECIDED and result is not None:
            if result.choice not in OPTIONS:  # a Decider that bypassed the contract
                detail = f"decision provider '{provider}' answered '{result.choice}' (not allowed)"
                run.warnings.append(f"{candidate.id}: {detail}")
                return ContextClassification.fallback(
                    Evidence.DECISION_INVALID_RESPONSE, detail, provider=provider, model=model
                )
            return ContextClassification(
                classification=ContextClass(result.choice), selected_by=SelectedBy.PROBABILISTIC,
                evidence=Evidence.DECISION_PROVIDER_JUDGEMENT,
                reason=f"judged {result.choice} by '{provider}' "
                       f"(confidence {result.confidence:.2f})",
                confidence=result.confidence, relevance=result.score, provider=provider,
                model=model,
            )
        detail = outcome.detail or str(outcome.fallback_reason)
        if outcome.fallback_reason is FallbackReason.LOW_CONFIDENCE and result is not None:
            suggestion = ContextClass(result.choice) if result.choice in OPTIONS else None
            return ContextClassification.fallback(
                Evidence.DECISION_LOW_CONFIDENCE, f"not accepted: {detail}",
                suggestion=suggestion, confidence=result.confidence, provider=provider,
                model=model,
            )
        if outcome.fallback_reason is FallbackReason.INVALID_RESPONSE:
            run.warnings.append(f"{candidate.id}: {detail}")
            return ContextClassification.fallback(
                Evidence.DECISION_INVALID_RESPONSE, detail, provider=provider
            )
        # UNAVAILABLE / TIMEOUT: the provider is down; do not keep calling it this run.
        run.stopped = f"decision provider '{provider}' {outcome.fallback_reason}: {detail}"
        run.warnings.append(run.stopped)
        return ContextClassification.fallback(Evidence.DECISION_UNAVAILABLE, run.stopped,
                                              provider=provider)

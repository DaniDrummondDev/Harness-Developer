"""Context Classification contracts (V1.2).

Classification answers "how important is this candidate for this request?",
never "how much fits?" or "what enters the prompt?" (V1.3+). Every candidate
receives exactly one class:

    class       meaning
    REQUIRED    must be available for a correct or safe execution; a later stage
                that cannot provide it has a serious problem (never dropped by budget)
    HIGH_VALUE  strongly related to the request; very likely improves the work
    OPTIONAL    possibly useful; its absence does not compromise the work
    EXCLUDED    discovered but not to be considered for selection (superseded,
                generated, unrelated...). Kept in the result for audit, never deleted

Who decided (`SelectedBy`), in the fixed order of decisions.yaml:

    DETERMINISTIC  a classification rule matched objective evidence (first match wins)
    PROBABILISTIC  the decision layer (Jev today) chose among EXCLUDED/OPTIONAL/
                   HIGH_VALUE with confidence >= decisions.yaml minimum_confidence.
                   It can never choose REQUIRED: that needs objective evidence
    FALLBACK       no rule matched and no confident decision exists: the
                   conservative class OPTIONAL (kept, never promoted, never dropped)

`Evidence` is the structured "why": for DETERMINISTIC it is the stable id of
the rule that decided; for FALLBACK it names why no decision was accepted.
`reason` complements it in human words. Invariants are validated here, so an
impossible combination (memory REQUIRED, probabilistic REQUIRED, fallback other
than OPTIONAL) cannot be constructed by any code path.

The classified candidate *wraps* the untouched `ContextCandidate` (composition,
no copied fields, no mutation).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestrator.context.models import KIND_ORDER, CandidateKind, ContextCandidate
from orchestrator.core.request import EngineeringRequest


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContextClass(StrEnum):
    """The official vocabulary (roadmap V1.2). Declaration order = priority."""

    REQUIRED = "REQUIRED"
    HIGH_VALUE = "HIGH_VALUE"
    OPTIONAL = "OPTIONAL"
    EXCLUDED = "EXCLUDED"


CLASS_ORDER = {cls: index for index, cls in enumerate(ContextClass)}

# What the probabilistic layer may answer, lowest value first (an ordered decision).
PROBABILISTIC_CLASSES = (ContextClass.EXCLUDED, ContextClass.OPTIONAL, ContextClass.HIGH_VALUE)
# The conservative class used whenever no rule matched and no confident decision exists.
FALLBACK_CLASS = ContextClass.OPTIONAL


class SelectedBy(StrEnum):
    DETERMINISTIC = "deterministic"
    PROBABILISTIC = "probabilistic"
    FALLBACK = "fallback"


class Evidence(StrEnum):
    # Deterministic rules: the value is the rule's stable id (deterministic.py).
    APPLICABLE_POLICY = "applicable_policy"
    EXPLICIT_SOURCE_REFERENCE = "explicit_source_reference"
    EXPLICIT_DOCUMENT_REFERENCE = "explicit_document_reference"
    EXPLICIT_LIBRARY_REFERENCE = "explicit_library_reference"
    PROJECT_INSTRUCTION = "project_instruction"
    GENERATED_ARTIFACT = "generated_artifact"
    SUPERSEDED_ADR = "superseded_adr"
    APPLICABLE_GUIDELINE = "applicable_guideline"
    APPLICABLE_LIBRARY_RULE = "applicable_library_rule"
    MATCHING_STACK = "matching_stack"
    MATCHING_CAPABILITY = "matching_capability"
    NAMED_DIRECTORY_ENTRY = "named_directory_entry"
    # Probabilistic layer.
    DECISION_PROVIDER_JUDGEMENT = "decision_provider_judgement"
    # Fallback: why no confident decision exists.
    NO_DECISION_LAYER = "no_decision_layer"
    DECISION_LIMIT_REACHED = "decision_limit_reached"
    UNSAFE_DECISION_INPUT = "unsafe_decision_input"
    DECISION_LOW_CONFIDENCE = "decision_low_confidence"
    DECISION_UNAVAILABLE = "decision_unavailable"
    DECISION_INVALID_RESPONSE = "decision_invalid_response"


DETERMINISTIC_EVIDENCE = frozenset({
    Evidence.APPLICABLE_POLICY, Evidence.EXPLICIT_SOURCE_REFERENCE,
    Evidence.EXPLICIT_DOCUMENT_REFERENCE, Evidence.EXPLICIT_LIBRARY_REFERENCE,
    Evidence.PROJECT_INSTRUCTION, Evidence.GENERATED_ARTIFACT, Evidence.SUPERSEDED_ADR,
    Evidence.APPLICABLE_GUIDELINE, Evidence.APPLICABLE_LIBRARY_RULE, Evidence.MATCHING_STACK,
    Evidence.MATCHING_CAPABILITY, Evidence.NAMED_DIRECTORY_ENTRY,
})
FALLBACK_EVIDENCE = frozenset({
    Evidence.NO_DECISION_LAYER, Evidence.DECISION_LIMIT_REACHED, Evidence.UNSAFE_DECISION_INPUT,
    Evidence.DECISION_LOW_CONFIDENCE, Evidence.DECISION_UNAVAILABLE,
    Evidence.DECISION_INVALID_RESPONSE,
})

class ContextClassification(_Model):
    """One classification and its audit trail.

    - `also_matched`: other deterministic rules that matched but did not decide
      (e.g. an explicitly named ADR that is also superseded);
    - `confidence` / `relevance`: probabilistic layer only (relevance = the ordered
      decision's score, 0 = EXCLUDED ... 1 = HIGH_VALUE);
    - `suggestion`: what the decision layer proposed when it was not accepted
      (low confidence) — audit only, never applied;
    - `provider` / `model`: who produced a probabilistic answer.
    """

    classification: ContextClass
    selected_by: SelectedBy
    evidence: Evidence
    reason: str = Field(min_length=1)
    also_matched: tuple[Evidence, ...] = ()
    confidence: float | None = Field(default=None, ge=0, le=1)
    relevance: float | None = Field(default=None, ge=0, le=1)
    suggestion: ContextClass | None = None
    provider: str | None = None
    model: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        audit = (self.confidence, self.relevance, self.suggestion, self.provider, self.model)
        if self.also_matched and (self.selected_by is not SelectedBy.DETERMINISTIC
                                  or not set(self.also_matched) <= DETERMINISTIC_EVIDENCE):
            raise ValueError("also_matched lists deterministic rules of a deterministic decision")
        if self.selected_by is SelectedBy.DETERMINISTIC:
            if self.evidence not in DETERMINISTIC_EVIDENCE:
                raise ValueError(f"'{self.evidence}' is not a deterministic rule")
            if any(value is not None for value in audit):
                raise ValueError("a deterministic decision carries no provider metrics")
        elif self.selected_by is SelectedBy.PROBABILISTIC:
            if self.evidence is not Evidence.DECISION_PROVIDER_JUDGEMENT:
                raise ValueError("a probabilistic decision has 'decision_provider_judgement'")
            if self.classification not in PROBABILISTIC_CLASSES:
                raise ValueError("the probabilistic layer cannot decide REQUIRED")
            if self.provider is None or self.confidence is None or self.suggestion is not None:
                raise ValueError("a probabilistic decision names its provider and confidence")
        else:
            if self.evidence not in FALLBACK_EVIDENCE:
                raise ValueError(f"'{self.evidence}' is not a fallback reason")
            if self.classification is not FALLBACK_CLASS:
                raise ValueError(f"the fallback class is {FALLBACK_CLASS}")
            if self.suggestion not in (None, *PROBABILISTIC_CLASSES):
                raise ValueError("a suggestion is one of the probabilistic classes")
        return self

    @classmethod
    def fallback(cls, evidence: Evidence, reason: str, *, suggestion: ContextClass | None = None,
                 confidence: float | None = None, provider: str | None = None,
                 model: str | None = None) -> ContextClassification:
        return cls(
            classification=FALLBACK_CLASS, selected_by=SelectedBy.FALLBACK, evidence=evidence,
            reason=reason, suggestion=suggestion, confidence=confidence, provider=provider,
            model=model,
        )


class ClassifiedContextCandidate(_Model):
    candidate: ContextCandidate
    classification: ContextClassification

    @model_validator(mode="after")
    def _memory_is_never_required(self) -> Self:
        # Memory is auxiliary context, never a source of truth (docs/01 §8).
        if (self.candidate.kind is CandidateKind.MEMORY
                and self.classification.classification is ContextClass.REQUIRED):
            raise ValueError("a memory can never be REQUIRED")
        return self

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (CLASS_ORDER[self.classification.classification],
                KIND_ORDER[self.candidate.kind], self.candidate.id)


class ContextClassificationResult(_Model):
    """Every discovered candidate, classified (EXCLUDED included), in a stable
    order: class priority, then candidate kind, then id. The order is output
    stability only — it is not a selection or a budget.

    `counts` / `decisions` are derived from `candidates` and validated against
    them (they exist so the JSON is self-describing). `warnings` holds discovery
    warnings (prefixed by discoverer) and classification warnings (prefixed
    `classification:`). `decision_provider` is the probabilistic provider
    available in this run (None = deterministic rules + fallback only).
    """

    request: EngineeringRequest
    candidates: tuple[ClassifiedContextCandidate, ...]
    counts: dict[ContextClass, int]
    decisions: dict[SelectedBy, int]
    warnings: tuple[str, ...] = ()
    decision_provider: str | None = None

    @classmethod
    def build(cls, request: EngineeringRequest, candidates: Sequence[ClassifiedContextCandidate],
              *, warnings: Sequence[str] = (),
              decision_provider: str | None = None) -> ContextClassificationResult:
        ordered = tuple(sorted(candidates, key=lambda c: c.sort_key))
        return cls(
            request=request, candidates=ordered, counts=_counts(ordered),
            decisions=_decisions(ordered), warnings=tuple(warnings),
            decision_provider=decision_provider,
        )

    @model_validator(mode="after")
    def _derived_fields_match(self) -> Self:
        if self.counts != _counts(self.candidates) or self.decisions != _decisions(self.candidates):
            raise ValueError("counts/decisions do not match the classified candidates")
        if list(self.candidates) != sorted(self.candidates, key=lambda c: c.sort_key):
            raise ValueError("candidates must be ordered by class, kind, id")
        return self

    def by_class(self, cls: ContextClass) -> tuple[ClassifiedContextCandidate, ...]:
        return tuple(c for c in self.candidates if c.classification.classification is cls)


def _counts(candidates: Sequence[ClassifiedContextCandidate]) -> dict[ContextClass, int]:
    found = Counter(c.classification.classification for c in candidates)
    return {cls: found[cls] for cls in ContextClass}


def _decisions(candidates: Sequence[ClassifiedContextCandidate]) -> dict[SelectedBy, int]:
    found = Counter(c.classification.selected_by for c in candidates)
    return {selector: found[selector] for selector in SelectedBy}

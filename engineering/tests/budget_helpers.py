"""Builders for V1.3 Context Budget tests (offline: no Jev, no network)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from classification_helpers import candidate, request

from orchestrator.config import BudgetSection, CategoryLimits
from orchestrator.context.budget.budgeter import ContextBudgeter
from orchestrator.context.budget.content import LoadedContent
from orchestrator.context.budget.models import ContextBudgetResult
from orchestrator.context.classification.models import (
    ClassifiedContextCandidate,
    ContextClass,
    ContextClassification,
    ContextClassificationResult,
    Evidence,
    SelectedBy,
)
from orchestrator.context.models import CandidateKind, ContextCandidate, MetadataValue
from orchestrator.core.request import EngineeringRequest

# A plausible deterministic rule per class (the budget never reads the evidence).
_RULE = {
    ContextClass.REQUIRED: Evidence.EXPLICIT_SOURCE_REFERENCE,
    ContextClass.HIGH_VALUE: Evidence.NAMED_DIRECTORY_ENTRY,
    ContextClass.OPTIONAL: Evidence.NAMED_DIRECTORY_ENTRY,
    ContextClass.EXCLUDED: Evidence.GENERATED_ARTIFACT,
}


def decision(cls: ContextClass, by: SelectedBy | None = None,
             confidence: float = 0.9) -> ContextClassification:
    """A valid classification; OPTIONAL defaults to the fallback, others to a rule."""
    by = by or (SelectedBy.FALLBACK if cls is ContextClass.OPTIONAL else SelectedBy.DETERMINISTIC)
    if by is SelectedBy.FALLBACK:
        return ContextClassification.fallback(Evidence.NO_DECISION_LAYER, "no decision layer")
    if by is SelectedBy.PROBABILISTIC:
        return ContextClassification(
            classification=cls, selected_by=by, evidence=Evidence.DECISION_PROVIDER_JUDGEMENT,
            reason="scripted judgement", confidence=confidence, provider="scripted",
        )
    return ContextClassification(classification=cls, selected_by=by, evidence=_RULE[cls],
                                 reason=f"rule for {cls}")


def item(kind: CandidateKind, path: str, cls: ContextClass, *, by: SelectedBy | None = None,
         confidence: float = 0.9,
         metadata: Mapping[str, MetadataValue] | None = None) -> ClassifiedContextCandidate:
    return ClassifiedContextCandidate(
        candidate=candidate(kind, path, metadata=metadata),
        classification=decision(cls, by, confidence),
    )


def classified(*items: ClassifiedContextCandidate,
               subject: EngineeringRequest | None = None) -> ContextClassificationResult:
    """`subject`: reuse one request (each `request()` has its own id and timestamp)."""
    return ContextClassificationResult.build(subject or request(), items)


def limits(total: int = 1000, reserve: int = 0, *, categories: Mapping[str, int] | None = None,
           **counts: Any) -> BudgetSection:
    """Generous item limits unless a test sets them."""
    values = {"max_files": 100, "max_adrs": 100, "max_memories": 100, **counts}
    return BudgetSection(total=total, reserve=reserve,
                         categories=CategoryLimits(**(categories or {})), **values)


class FakeLoader:
    """Text by candidate id (`size` chars of 'x' when given an int); records what it loaded."""

    def __init__(self, texts: Mapping[str, str | int]) -> None:
        self._texts = {key: "x" * v if isinstance(v, int) else v for key, v in texts.items()}
        self.loaded: list[str] = []

    def load(self, candidate: ContextCandidate) -> LoadedContent:
        self.loaded.append(candidate.id)
        text = self._texts.get(candidate.id)
        return LoadedContent(text=text) if text is not None else LoadedContent(
            problem=f"no text for {candidate.id}")


def run(budget: BudgetSection, sizes: Mapping[str, str | int],
        *items: ClassifiedContextCandidate) -> tuple[ContextBudgetResult, FakeLoader]:
    loader = FakeLoader(sizes)
    return ContextBudgeter(budget, loader).budget(classified(*items)), loader


def ids(items: tuple[Any, ...]) -> list[str]:
    return [i.candidate.id for i in items]


def reasons(result: ContextBudgetResult) -> dict[str, str]:
    return {i.candidate.id: i.reason.value for i in result.items}

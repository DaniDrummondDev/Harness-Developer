"""`EscalationEvaluator`: ContextBudgetResult -> ContextEscalationDecision (V1.4).

Pure and deterministic: it reads only what V1.0-V1.3 already produced (the
request's declared intent, the classification of every candidate, discovery's
merge metadata and the budget outcome) and compares it with context.yaml
`escalation.triggers`. It never calls a provider: whether to call the LLM is
not a question for an LLM.

    reason                        fires when                                  threshold
    architectural_task            request.intent in architectural_intents     list ([] = off)
    multiple_domains              specialties classified REQUIRED/HIGH_VALUE  min_specialties
                                  >= min_specialties
    low_confidence                candidates the decision layer answered      min_low_confidence
                                  below its threshold (fallback evidence
                                  decision_low_confidence) >= N
    too_many_relevant_candidates  HIGH_VALUE candidates > max_high_value      max_high_value
    source_conflict               a non-EXCLUDED candidate carries discovery  always on
                                  `merge_conflicts` metadata
    required_overflow             budget usage.overflow > 0                   always on
    required_unavailable          a REQUIRED candidate has no loadable        always on
                                  content (budget content_unavailable)

Deliberately NOT signals: the `no_decision_layer` fallback (a configuration
state, true for every request while Jev is disabled, not uncertainty about this
request), candidate text (no NLP over instructions) and risk (no risk source
before the risk engine, V9).
"""

from __future__ import annotations

from orchestrator.config import EscalationSection
from orchestrator.context.budget.models import ContextBudgetResult
from orchestrator.context.classification.models import ContextClass, Evidence
from orchestrator.context.escalation.models import (
    ContextEscalationDecision,
    EscalationEvidence,
    EscalationReason,
)
from orchestrator.context.models import MERGE_CONFLICTS_KEY, CandidateKind

_RELEVANT = frozenset({ContextClass.REQUIRED, ContextClass.HIGH_VALUE})


class EscalationEvaluator:
    def __init__(self, settings: EscalationSection) -> None:
        self._settings = settings

    def evaluate(self, budget: ContextBudgetResult) -> ContextEscalationDecision:
        if not self._settings.enabled:
            return ContextEscalationDecision(required=False, evaluated=False)
        evidence = [
            found for found in (
                self._architectural(budget), self._domains(budget), self._low_confidence(budget),
                self._high_value(budget), self._source_conflict(budget),
                self._overflow(budget), self._unavailable(budget),
            ) if found is not None
        ]
        return ContextEscalationDecision.of(tuple(evidence))

    def _architectural(self, budget: ContextBudgetResult) -> EscalationEvidence | None:
        intent = budget.request.intent
        if intent not in self._settings.triggers.architectural_intents:
            return None
        return EscalationEvidence(
            reason=EscalationReason.ARCHITECTURAL_TASK,
            detail=f"declared intent '{intent}' is configured as architectural work",
        )

    def _domains(self, budget: ContextBudgetResult) -> EscalationEvidence | None:
        threshold = self._settings.triggers.min_specialties
        ids = tuple(i.candidate.id for i in budget.items
                    if i.candidate.kind is CandidateKind.SPECIALTY
                    and i.classified.classification.classification in _RELEVANT)
        if threshold is None or len(ids) < threshold:
            return None
        return EscalationEvidence(
            reason=EscalationReason.MULTIPLE_DOMAINS, observed=len(ids), threshold=threshold,
            detail=f"{len(ids)} specialties are REQUIRED/HIGH_VALUE (>= {threshold})",
            candidate_ids=ids,
        )

    def _low_confidence(self, budget: ContextBudgetResult) -> EscalationEvidence | None:
        threshold = self._settings.triggers.min_low_confidence
        ids = tuple(i.candidate.id for i in budget.items
                    if i.classified.classification.evidence is Evidence.DECISION_LOW_CONFIDENCE)
        if threshold is None or len(ids) < threshold:
            return None
        return EscalationEvidence(
            reason=EscalationReason.LOW_CONFIDENCE, observed=len(ids), threshold=threshold,
            detail=f"{len(ids)} candidates were answered below the decision threshold and fell "
                   f"back to OPTIONAL (>= {threshold})",
            candidate_ids=ids,
        )

    def _high_value(self, budget: ContextBudgetResult) -> EscalationEvidence | None:
        threshold = self._settings.triggers.max_high_value
        ids = tuple(i.candidate.id for i in budget.items
                    if i.classified.classification.classification is ContextClass.HIGH_VALUE)
        if threshold is None or len(ids) <= threshold:
            return None
        return EscalationEvidence(
            reason=EscalationReason.TOO_MANY_RELEVANT_CANDIDATES, observed=len(ids),
            threshold=threshold, detail=f"{len(ids)} HIGH_VALUE candidates (> {threshold})",
            candidate_ids=ids,
        )

    @staticmethod
    def _source_conflict(budget: ContextBudgetResult) -> EscalationEvidence | None:
        ids = tuple(i.candidate.id for i in (*budget.selected, *budget.not_selected)
                    if i.candidate.metadata.get(MERGE_CONFLICTS_KEY))
        if not ids:
            return None
        return EscalationEvidence(
            reason=EscalationReason.SOURCE_CONFLICT, observed=len(ids),
            detail=f"{len(ids)} candidates carry conflicting metadata from different sources",
            candidate_ids=ids,
        )

    @staticmethod
    def _overflow(budget: ContextBudgetResult) -> EscalationEvidence | None:
        usage = budget.usage
        if not usage.overflow:
            return None
        return EscalationEvidence(
            reason=EscalationReason.REQUIRED_OVERFLOW, observed=usage.used, threshold=usage.usable,
            detail=f"REQUIRED context ({usage.used} characters) exceeds the usable budget "
                   f"({usage.usable}) by {usage.overflow}",
            candidate_ids=tuple(i.candidate.id for i in budget.selected
                                if i.classified.classification.classification
                                is ContextClass.REQUIRED),
        )

    @staticmethod
    def _unavailable(budget: ContextBudgetResult) -> EscalationEvidence | None:
        ids = tuple(i.candidate.id for i in budget.not_selected
                    if i.classified.classification.classification is ContextClass.REQUIRED)
        if not ids:
            return None
        return EscalationEvidence(
            reason=EscalationReason.REQUIRED_UNAVAILABLE, observed=len(ids),
            detail=f"{len(ids)} REQUIRED candidates have no loadable content",
            candidate_ids=ids,
        )

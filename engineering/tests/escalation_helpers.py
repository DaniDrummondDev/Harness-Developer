"""Builders for V1.4 LLM Context Escalation tests (offline: no LLM, no network).

`ScriptedLLMProvider` is a test-only LLMProvider (the package `FakeLLMProvider`
stays generic and knows nothing about ContextPlan): it answers a fixed text, or a
text computed from the prompt, or raises the given ProviderError.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from budget_helpers import FakeLoader, classified, limits
from classification_helpers import candidate

from orchestrator.config import BudgetSection, EscalationSection, EscalationTriggers
from orchestrator.context.budget.budgeter import ContextBudgeter
from orchestrator.context.budget.models import ContextBudgetResult
from orchestrator.context.classification.models import (
    ClassifiedContextCandidate,
    ContextClass,
    ContextClassification,
    Evidence,
)
from orchestrator.context.escalation.evaluator import EscalationEvaluator
from orchestrator.context.escalation.models import ContextEscalationResult
from orchestrator.context.escalation.planner import ContextEscalation, ContextPlanner
from orchestrator.context.models import CandidateKind, MetadataValue
from orchestrator.core.exceptions import ProviderError
from orchestrator.intake import normalize_request
from orchestrator.providers.base import LLMRequest, LLMResult
from orchestrator.providers.resolution import ResolvedModel

PLANNER_MODEL = ResolvedModel(alias="context_planner", provider="scripted-llm",
                              model_id="planner-v1")


class ScriptedLLMProvider:
    provider_id = "scripted-llm"

    def __init__(self, answer: str | Callable[[str], str] = "", *,
                 fail: ProviderError | None = None) -> None:
        self._answer = answer
        self._fail = fail
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        if self._fail is not None:
            raise self._fail
        text = self._answer(request.prompt) if callable(self._answer) else self._answer
        return LLMResult(provider=self.provider_id, model=request.model, text=text)


def plan_json(ids: Iterable[str], *, rationale: str = "policies first, then the named code",
              unresolved: Sequence[str] = (), suggestions: Sequence[str] = (),
              **extra: Any) -> str:
    return json.dumps({"selected_candidate_ids": list(ids), "rationale": rationale,
                       "unresolved_constraints": list(unresolved),
                       "suggestions": list(suggestions), **extra})


def prompt_input(prompt: str) -> dict[str, Any]:
    """The JSON input embedded at the end of the planner prompt."""
    data: dict[str, Any] = json.loads(prompt[prompt.index("Input (JSON):\n") + 14:])
    return data


def settings(*, enabled: bool = True, intents: Sequence[str] = ("plan",),
             min_specialties: int | None = 3, max_high_value: int | None = 12,
             min_low_confidence: int | None = 3, model: str | None = None) -> EscalationSection:
    return EscalationSection(enabled=enabled, model=model, triggers=EscalationTriggers(
        architectural_intents=list(intents),  # type: ignore[arg-type]
        min_specialties=min_specialties, max_high_value=max_high_value,
        min_low_confidence=min_low_confidence))


def low_confidence(kind: CandidateKind, path: str) -> ClassifiedContextCandidate:
    """A fallback OPTIONAL: the decision layer answered below its threshold."""
    return ClassifiedContextCandidate(
        candidate=candidate(kind, path),
        classification=ContextClassification.fallback(
            Evidence.DECISION_LOW_CONFIDENCE, "confidence 0.55 below 0.70",
            suggestion=ContextClass.HIGH_VALUE, confidence=0.55, provider="scripted"),
    )


def budget_of(sizes: Mapping[str, str | int], *items: ClassifiedContextCandidate,
              budget: BudgetSection | None = None, intent: str | None = None,
              instruction: str = "fix the invoice rounding") -> ContextBudgetResult:
    subject = normalize_request(source="cli", instruction=instruction, intent=intent)
    return ContextBudgeter(budget or limits(), FakeLoader(sizes)).budget(
        classified(*items, subject=subject))


def escalate(budget: ContextBudgetResult, llm: ScriptedLLMProvider | None = None,
             section: EscalationSection | None = None) -> ContextEscalationResult:
    planner = ContextPlanner(llm, PLANNER_MODEL, clock=_ticks()) if llm is not None else None
    return ContextEscalation(EscalationEvaluator(section or settings()), planner).escalate(budget)


def _ticks() -> Callable[[], float]:
    values = iter([10.0, 10.25, 20.0, 20.5])
    return lambda: next(values)


def meta(**values: MetadataValue) -> dict[str, MetadataValue]:
    return dict(values)

"""V1.4 escalation decision: deterministic triggers over the V1.3 budget result."""

from __future__ import annotations

import pytest
from budget_helpers import item, limits
from escalation_helpers import (
    ScriptedLLMProvider,
    budget_of,
    escalate,
    low_confidence,
    meta,
    settings,
)
from pydantic import ValidationError

from orchestrator.context.classification.models import ContextClass
from orchestrator.context.escalation.evaluator import EscalationEvaluator
from orchestrator.context.escalation.models import (
    ContextEscalationDecision,
    EscalationEvidence,
    EscalationReason,
    PlanStatus,
)
from orchestrator.context.models import MERGE_CONFLICTS_KEY, CandidateKind

R = ContextClass.REQUIRED
H = ContextClass.HIGH_VALUE
O = ContextClass.OPTIONAL  # noqa: E741
X = ContextClass.EXCLUDED
SRC = CandidateKind.SOURCE_CODE


def simple() -> list:  # type: ignore[type-arg]
    return [item(CandidateKind.POLICY, "secrets", R), item(SRC, "src/a.py", R),
            item(SRC, "src/b.py", H), item(CandidateKind.DOCUMENTATION, "docs/x.md", O),
            item(SRC, "yarn.lock", X)]


SIZES = {"policy/secrets": 10, "source/src/a.py": 10, "source/src/b.py": 10,
         "doc/docs/x.md": 10}


def reasons(**kwargs: object) -> tuple[EscalationReason, ...]:
    budget = kwargs.pop("budget")
    return EscalationEvaluator(settings(**kwargs)).evaluate(budget).reasons  # type: ignore[arg-type]


def test_simple_request_does_not_escalate_and_calls_no_llm() -> None:
    llm = ScriptedLLMProvider()
    result = escalate(budget_of(SIZES, *simple()), llm)
    assert result.escalation == ContextEscalationDecision(required=False)
    assert result.status is PlanStatus.NOT_REQUIRED
    assert (result.llm_calls, llm.requests, result.plan, result.call) == (0, [], None, None)


def test_architectural_intent_escalates_with_its_evidence() -> None:
    decision = EscalationEvaluator(settings()).evaluate(budget_of(SIZES, *simple(), intent="plan"))
    assert decision.required and decision.reasons == (EscalationReason.ARCHITECTURAL_TASK,)
    assert "'plan'" in decision.evidence[0].detail


@pytest.mark.parametrize("intent", [None, "implement", "review"])
def test_other_intents_are_not_architectural(intent: str | None) -> None:
    assert reasons(budget=budget_of(SIZES, *simple(), intent=intent)) == ()


def test_architectural_trigger_can_be_disabled() -> None:
    assert reasons(budget=budget_of(SIZES, *simple(), intent="plan"), intents=()) == ()


def test_multiple_domains_counts_relevant_specialties_only() -> None:
    specialties = [item(CandidateKind.SPECIALTY, name, cls) for name, cls in
                   (("python", H), ("security", H), ("database", R), ("docker", O))]
    budget = budget_of({f"specialty/{n}": 5 for n in ("python", "security", "database", "docker")},
                       *specialties)
    decision = EscalationEvaluator(settings()).evaluate(budget)
    assert decision.reasons == (EscalationReason.MULTIPLE_DOMAINS,)
    assert decision.evidence[0].observed == 3 and decision.evidence[0].threshold == 3
    assert set(decision.evidence[0].candidate_ids) == {
        "specialty/python", "specialty/security", "specialty/database"}
    assert reasons(budget=budget, min_specialties=4) == ()
    assert reasons(budget=budget, min_specialties=None) == ()


def test_many_high_value_candidates_escalate_above_the_threshold() -> None:
    many = [item(SRC, f"src/m{i}.py", H) for i in range(4)]
    budget = budget_of({f"source/src/m{i}.py": 5 for i in range(4)}, *many)
    assert reasons(budget=budget, max_high_value=4) == ()
    assert reasons(budget=budget, max_high_value=3) == (
        EscalationReason.TOO_MANY_RELEVANT_CANDIDATES,)
    evidence = EscalationEvaluator(settings(max_high_value=3)).evaluate(budget).evidence[0]
    assert (evidence.observed, evidence.threshold) == (4, 3)


def test_low_confidence_counts_decisions_below_threshold_not_the_disabled_layer() -> None:
    unsure = [low_confidence(CandidateKind.DOCUMENTATION, f"docs/u{i}.md") for i in range(3)]
    no_layer = [item(CandidateKind.DOCUMENTATION, f"docs/n{i}.md", O) for i in range(5)]
    sizes = {f"doc/docs/{p}{i}.md": 5 for p in "un" for i in range(5)}
    assert reasons(budget=budget_of(sizes, *unsure, *no_layer)) == (
        EscalationReason.LOW_CONFIDENCE,)
    # the no_decision_layer fallback is configuration, not uncertainty: never a trigger
    assert reasons(budget=budget_of(sizes, *no_layer)) == ()
    assert reasons(budget=budget_of(sizes, *unsure[:2])) == ()


def test_source_conflict_from_discovery_merge_metadata() -> None:
    conflicted = item(CandidateKind.DOCUMENTATION, "docs/x.md", O,
                      metadata=meta(**{MERGE_CONFLICTS_KEY: ("status: kept 'a', dropped 'b'",)}))
    decision = EscalationEvaluator(settings()).evaluate(budget_of(SIZES, conflicted))
    assert decision.reasons == (EscalationReason.SOURCE_CONFLICT,)
    assert decision.evidence[0].candidate_ids == ("doc/docs/x.md",)


def test_conflict_on_an_excluded_candidate_is_not_a_trigger() -> None:
    excluded = item(SRC, "yarn.lock", X, metadata=meta(**{MERGE_CONFLICTS_KEY: ("k: a vs b",)}))
    assert reasons(budget=budget_of({}, excluded)) == ()


def test_required_overflow_escalates_with_sizes() -> None:
    budget = budget_of({"policy/secrets": 60, "source/src/a.py": 60},
                       item(CandidateKind.POLICY, "secrets", R), item(SRC, "src/a.py", R),
                       budget=limits(total=100))
    decision = EscalationEvaluator(settings()).evaluate(budget)
    assert decision.reasons == (EscalationReason.REQUIRED_OVERFLOW,)
    evidence = decision.evidence[0]
    assert (evidence.observed, evidence.threshold) == (120, 100)
    assert "by 20" in evidence.detail


def test_required_unavailable_escalates() -> None:
    budget = budget_of({"policy/secrets": 5}, item(CandidateKind.POLICY, "secrets", R),
                       item(SRC, "src/image.bin", R))
    decision = EscalationEvaluator(settings()).evaluate(budget)
    assert decision.reasons == (EscalationReason.REQUIRED_UNAVAILABLE,)
    assert decision.evidence[0].candidate_ids == ("source/src/image.bin",)


def test_multiple_triggers_are_all_recorded_in_declaration_order() -> None:
    specialties = [item(CandidateKind.SPECIALTY, n, H) for n in ("a", "b", "c")]
    unsure = [low_confidence(CandidateKind.DOCUMENTATION, f"docs/u{i}.md") for i in range(3)]
    sizes = {**{f"specialty/{n}": 30 for n in "abc"}, **{f"doc/docs/u{i}.md": 5 for i in range(3)},
             "source/src/a.py": 90}
    budget = budget_of(sizes, *specialties, *unsure, item(SRC, "src/a.py", R),
                       item(SRC, "src/gone.py", R), budget=limits(total=80), intent="plan")
    decision = EscalationEvaluator(settings(max_high_value=2)).evaluate(budget)
    assert decision.reasons == (
        EscalationReason.ARCHITECTURAL_TASK, EscalationReason.MULTIPLE_DOMAINS,
        EscalationReason.LOW_CONFIDENCE, EscalationReason.TOO_MANY_RELEVANT_CANDIDATES,
        EscalationReason.REQUIRED_OVERFLOW, EscalationReason.REQUIRED_UNAVAILABLE,
    )
    assert len(decision.evidence) == 6


def test_disabled_escalation_evaluates_nothing() -> None:
    budget = budget_of({}, item(SRC, "src/gone.py", R), intent="plan")
    result = escalate(budget, ScriptedLLMProvider(), settings(enabled=False))
    assert not result.escalation.evaluated and not result.escalation.required
    assert result.status is PlanStatus.NOT_REQUIRED and result.llm_calls == 0
    assert any("disabled" in w for w in result.warnings)


def test_decision_model_invariants() -> None:
    evidence = EscalationEvidence(reason=EscalationReason.SOURCE_CONFLICT, detail="x")
    with pytest.raises(ValidationError, match="exactly when a trigger fired"):
        ContextEscalationDecision(required=False, reasons=(evidence.reason,), evidence=(evidence,))
    with pytest.raises(ValidationError, match="evidence reasons"):
        ContextEscalationDecision(required=True, reasons=(EscalationReason.REQUIRED_OVERFLOW,),
                                  evidence=(evidence,))
    with pytest.raises(ValidationError, match="once"):
        ContextEscalationDecision.of((evidence, evidence))
    with pytest.raises(ValidationError, match="disabled"):
        ContextEscalationDecision(required=True, reasons=(evidence.reason,), evidence=(evidence,),
                                  evaluated=False)

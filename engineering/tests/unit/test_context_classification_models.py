"""V1.2 Context Classification contracts: vocabulary, invariants, aggregation, serialization."""

from __future__ import annotations

import pytest
from classification_helpers import candidate, request
from pydantic import ValidationError

from orchestrator.context.classification.models import (
    FALLBACK_CLASS,
    ClassifiedContextCandidate,
    ContextClass,
    ContextClassification,
    ContextClassificationResult,
    Evidence,
    SelectedBy,
)
from orchestrator.context.models import CandidateKind

DET = {"selected_by": SelectedBy.DETERMINISTIC, "reason": "rule"}


def deterministic(cls: ContextClass, evidence: Evidence = Evidence.APPLICABLE_POLICY,
                  **extra: object) -> ContextClassification:
    return ContextClassification(classification=cls, evidence=evidence, **DET, **extra)  # type: ignore[arg-type]


def probabilistic(cls: ContextClass, confidence: float = 0.9) -> ContextClassification:
    return ContextClassification(
        classification=cls, selected_by=SelectedBy.PROBABILISTIC,
        evidence=Evidence.DECISION_PROVIDER_JUDGEMENT, reason="judged", confidence=confidence,
        relevance=0.5, provider="jev", model="jev-1",
    )


def classified(kind: CandidateKind, path: str, k: ContextClassification
               ) -> ClassifiedContextCandidate:
    return ClassifiedContextCandidate(candidate=candidate(kind, path), classification=k)


# --- vocabulary -----------------------------------------------------------------------------


def test_exactly_the_four_official_classes_in_priority_order() -> None:
    assert [c.value for c in ContextClass] == ["REQUIRED", "HIGH_VALUE", "OPTIONAL", "EXCLUDED"]


def test_selected_by_is_a_closed_vocabulary() -> None:
    assert [s.value for s in SelectedBy] == ["deterministic", "probabilistic", "fallback"]
    with pytest.raises(ValidationError):
        ContextClassification(classification=ContextClass.OPTIONAL, selected_by="llm",  # type: ignore[arg-type]
                              evidence=Evidence.NO_DECISION_LAYER, reason="x")


def test_fallback_class_is_the_conservative_optional() -> None:
    assert FALLBACK_CLASS is ContextClass.OPTIONAL


# --- invariants -------------------------------------------------------------------------------


def test_deterministic_decision_carries_no_provider_metrics() -> None:
    assert deterministic(ContextClass.REQUIRED).confidence is None
    with pytest.raises(ValidationError, match="no provider metrics"):
        deterministic(ContextClass.REQUIRED, confidence=0.9)
    with pytest.raises(ValidationError, match="not a deterministic rule"):
        deterministic(ContextClass.REQUIRED, Evidence.DECISION_PROVIDER_JUDGEMENT)


def test_probabilistic_layer_can_never_be_required() -> None:
    for cls in (ContextClass.HIGH_VALUE, ContextClass.OPTIONAL, ContextClass.EXCLUDED):
        assert probabilistic(cls).classification is cls
    with pytest.raises(ValidationError, match="cannot decide REQUIRED"):
        probabilistic(ContextClass.REQUIRED)


def test_probabilistic_decision_names_provider_and_confidence() -> None:
    with pytest.raises(ValidationError, match="provider and confidence"):
        ContextClassification(classification=ContextClass.OPTIONAL,
                              selected_by=SelectedBy.PROBABILISTIC,
                              evidence=Evidence.DECISION_PROVIDER_JUDGEMENT, reason="x")


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_is_a_probability(confidence: float) -> None:
    with pytest.raises(ValidationError):
        probabilistic(ContextClass.OPTIONAL, confidence=confidence)


def test_fallback_is_always_optional_with_a_fallback_reason() -> None:
    fallback = ContextClassification.fallback(
        Evidence.DECISION_LOW_CONFIDENCE, "below threshold", suggestion=ContextClass.EXCLUDED,
        confidence=0.4, provider="jev",
    )
    assert (fallback.classification, fallback.selected_by) == (
        ContextClass.OPTIONAL, SelectedBy.FALLBACK,
    )
    with pytest.raises(ValidationError, match="fallback class"):
        ContextClassification(classification=ContextClass.HIGH_VALUE,
                              selected_by=SelectedBy.FALLBACK,
                              evidence=Evidence.NO_DECISION_LAYER, reason="x")
    with pytest.raises(ValidationError, match="not a fallback reason"):
        ContextClassification.fallback(Evidence.APPLICABLE_POLICY, "x")
    with pytest.raises(ValidationError, match="suggestion"):
        ContextClassification.fallback(Evidence.DECISION_LOW_CONFIDENCE, "x",
                                       suggestion=ContextClass.REQUIRED)


def test_also_matched_belongs_to_deterministic_decisions() -> None:
    k = deterministic(ContextClass.REQUIRED, Evidence.EXPLICIT_DOCUMENT_REFERENCE,
                      also_matched=(Evidence.SUPERSEDED_ADR,))
    assert k.also_matched == (Evidence.SUPERSEDED_ADR,)
    with pytest.raises(ValidationError, match="also_matched"):
        deterministic(ContextClass.REQUIRED, also_matched=(Evidence.NO_DECISION_LAYER,))


def test_memory_can_never_be_required() -> None:
    memory = candidate(CandidateKind.MEMORY, "m-1")
    with pytest.raises(ValidationError, match="memory can never be REQUIRED"):
        ClassifiedContextCandidate(candidate=memory,
                                   classification=deterministic(ContextClass.REQUIRED))
    assert ClassifiedContextCandidate(
        candidate=memory, classification=probabilistic(ContextClass.HIGH_VALUE)
    ).classification.classification is ContextClass.HIGH_VALUE


def test_classification_does_not_copy_or_mutate_the_candidate() -> None:
    original = candidate(CandidateKind.DOCUMENTATION, "docs/a.md")
    wrapped = ClassifiedContextCandidate(candidate=original,
                                         classification=probabilistic(ContextClass.OPTIONAL))
    assert wrapped.candidate == original
    assert set(wrapped.model_dump()) == {"candidate", "classification"}
    with pytest.raises(ValidationError):
        wrapped.candidate.title = "changed"  # type: ignore[misc]


# --- aggregate result ---------------------------------------------------------------------------


def _mixed() -> list[ClassifiedContextCandidate]:
    return [
        classified(CandidateKind.SOURCE_CODE, "b.py", probabilistic(ContextClass.EXCLUDED)),
        classified(CandidateKind.DOCUMENTATION, "z.md",
                   ContextClassification.fallback(Evidence.NO_DECISION_LAYER, "none")),
        classified(CandidateKind.SOURCE_CODE, "a.py",
                   deterministic(ContextClass.REQUIRED, Evidence.EXPLICIT_SOURCE_REFERENCE)),
        classified(CandidateKind.POLICY, "secrets", deterministic(ContextClass.REQUIRED)),
        classified(CandidateKind.MEMORY, "m-1", probabilistic(ContextClass.HIGH_VALUE)),
    ]


def test_result_orders_by_class_then_kind_then_id_and_counts() -> None:
    result = ContextClassificationResult.build(request(), _mixed(), warnings=("w",))
    assert [c.candidate.id for c in result.candidates] == [
        "policy/secrets", "source/a.py", "memory/m-1", "doc/z.md", "source/b.py",
    ]
    assert result.counts == {ContextClass.REQUIRED: 2, ContextClass.HIGH_VALUE: 1,
                             ContextClass.OPTIONAL: 1, ContextClass.EXCLUDED: 1}
    assert result.decisions == {SelectedBy.DETERMINISTIC: 2, SelectedBy.PROBABILISTIC: 2,
                                SelectedBy.FALLBACK: 1}
    assert [c.candidate.id for c in result.by_class(ContextClass.EXCLUDED)] == ["source/b.py"]


def test_result_rejects_inconsistent_counts_or_order() -> None:
    good = ContextClassificationResult.build(request(), _mixed())
    with pytest.raises(ValidationError, match="counts"):
        ContextClassificationResult(
            request=good.request, candidates=good.candidates,
            counts={**good.counts, ContextClass.REQUIRED: 9}, decisions=good.decisions,
        )
    with pytest.raises(ValidationError, match="ordered"):
        ContextClassificationResult(
            request=good.request, candidates=tuple(reversed(good.candidates)),
            counts=good.counts, decisions=good.decisions,
        )


def test_result_serialization_round_trips_and_is_stable() -> None:
    req = request()
    first = ContextClassificationResult.build(req, _mixed(), decision_provider="jev")
    second = ContextClassificationResult.build(req, list(reversed(_mixed())),
                                               decision_provider="jev")
    assert first.model_dump_json() == second.model_dump_json()
    data = first.model_dump(mode="json")
    assert data["counts"] == {"REQUIRED": 2, "HIGH_VALUE": 1, "OPTIONAL": 1, "EXCLUDED": 1}
    assert data["candidates"][0]["classification"]["selected_by"] == "deterministic"
    assert ContextClassificationResult.model_validate_json(first.model_dump_json()) == first
    assert "budget" not in data and "tokens" not in data

"""Request/result models of the provider contracts, and the fake adapters' behaviour."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.core.exceptions import (
    DecisionTimeoutError,
    HarnessError,
    ProviderCallError,
    ProviderError,
)
from orchestrator.providers.base import (
    DecisionKind,
    DecisionRequest,
    DecisionResult,
    LLMRequest,
    LLMResult,
)
from orchestrator.providers.fake import FakeDecisionProvider, FakeLLMProvider, FakeVendorError

# --- typed requests / results -----------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "", "prompt": "x"},
        {"model": "m", "prompt": "   "},
        {"model": "m", "prompt": "x", "temperature": 0.2},  # extra fields are rejected
    ],
)
def test_llm_request_rejects_invalid_input(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LLMRequest.model_validate(kwargs)


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (("only",), "at least 2"),
        (("a", "a"), "unique"),
        (("a", " "), "at least 1 character"),
    ],
)
def test_decision_request_requires_distinct_options(
    options: tuple[str, ...], expected: str
) -> None:
    with pytest.raises(ValidationError, match=expected):
        DecisionRequest(model="m", question="q?", options=options)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_decision_confidence_is_a_probability(confidence: float) -> None:
    with pytest.raises(ValidationError):
        DecisionResult(provider="p", model="m", choice="a", confidence=confidence)


def test_contract_models_are_immutable() -> None:
    result = LLMResult(provider="p", model="m", text="t")
    with pytest.raises(ValidationError, match="frozen"):
        result.text = "changed"  # type: ignore[misc]


def test_contracts_do_not_share_request_types() -> None:
    assert not issubclass(LLMRequest, DecisionRequest)
    assert not issubclass(DecisionRequest, LLMRequest)
    assert set(LLMRequest.model_fields) == {"model", "prompt"}
    # V0.4 evolved the decision request additively (all new fields are optional).
    assert set(DecisionRequest.model_fields) == {
        "model", "question", "options", "kind", "subject", "ordered", "descriptions",
    }
    assert DecisionRequest(model="m", question="q?", options=("a", "b")).ordered is False


# --- fake adapters ------------------------------------------------------------------


def test_fake_llm_is_deterministic_and_records_requests() -> None:
    fake = FakeLLMProvider("fake-a")
    request = LLMRequest(model="m1", prompt="hello")

    first, second = fake.complete(request), fake.complete(request)

    assert first == second == LLMResult(provider="fake-a", model="m1", text="[fake-a/m1] hello")
    assert fake.requests == [request, request]


def test_fake_decision_is_deterministic() -> None:
    fake = FakeDecisionProvider("fake-d", confidence=0.7)
    request = DecisionRequest(model="m", question="route?", options=("x", "y"))

    first, second = fake.decide(request), fake.decide(request)

    assert first == second
    assert (first.choice, first.confidence) == ("x", 0.7)
    assert fake.requests == [request, request]


def test_fake_translates_vendor_error_into_provider_call_error() -> None:
    fake = FakeLLMProvider("fake-a", fail_with="503 upstream")

    with pytest.raises(ProviderCallError) as excinfo:
        fake.complete(LLMRequest(model="m", prompt="p"))

    error = excinfo.value
    assert error.provider_id == "fake-a"
    assert str(error) == "provider 'fake-a' call failed: 503 upstream"
    assert isinstance(error.__cause__, FakeVendorError)  # chained, never leaked raw
    assert isinstance(error, ProviderError)
    assert isinstance(error, HarnessError)  # the CLI treats it as an expected failure


# --- V0.4: typed decisions and the evolved fake ---------------------------------------------------


def test_v02_style_decision_objects_remain_valid() -> None:
    request = DecisionRequest(model="m", question="q?", options=("a", "b"))
    result = DecisionResult(provider="p", model="m", choice="a", confidence=0.5)
    assert (request.kind, request.ordered, request.subject) == ("classification", False, None)
    assert (result.score, result.probability, result.probabilities) == (None, None, {})


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"probabilities": {"b": 1.0}}, "choice is missing from probabilities"),
        ({"probabilities": {"a": 0.5, "b": 0.3}}, "must sum to 1"),
        ({"score": 1.2}, "less than or equal to 1"),
        ({"probability": -0.1}, "greater than or equal to 0"),
        ({"kind": "workflow"}, "kind"),
        ({"input_tokens": -1}, "input_tokens"),
    ],
)
def test_decision_result_metrics_are_validated(fields: dict[str, object], expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        DecisionResult.model_validate(
            {"provider": "p", "model": "m", "choice": "a", "confidence": 0.5, **fields}
        )


def test_decision_request_descriptions_must_name_options() -> None:
    with pytest.raises(ValidationError, match="unknown options"):
        DecisionRequest(model="m", question="q?", options=("a", "b"), descriptions={"c": "x"})


def test_fake_decision_custom_score_choice_and_kind() -> None:
    request = DecisionRequest(
        model="m", question="sev?", options=("low", "mid", "high"),
        kind=DecisionKind.SEVERITY, ordered=True,
    )
    assert FakeDecisionProvider(choice="high").decide(request).score == 1.0  # derived position
    custom = FakeDecisionProvider(choice="mid", score=0.4, confidence=0.3).decide(request)
    assert (custom.choice, custom.score, custom.confidence, custom.kind) == (
        "mid", 0.4, 0.3, DecisionKind.SEVERITY,
    )


def test_fake_simulates_timeout_and_invalid_choice() -> None:
    request = DecisionRequest(model="m", question="q?", options=("a", "b"))
    with pytest.raises(DecisionTimeoutError, match="provider 'fake-decision' call failed: slow"):
        FakeDecisionProvider(fail_with="slow", fail_as=DecisionTimeoutError).decide(request)
    # The fake can break the contract on purpose; the decision service must catch it.
    assert FakeDecisionProvider(choice="z").decide(request).choice == "z"


def test_failed_call_is_still_recorded() -> None:
    fake = FakeDecisionProvider(fail_with="boom")
    with pytest.raises(ProviderCallError):
        fake.decide(DecisionRequest(model="m", question="q?", options=("a", "b")))
    assert len(fake.requests) == 1

"""Request/result models of the provider contracts, and the fake adapters' behaviour."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.core.exceptions import HarnessError, ProviderCallError, ProviderError
from orchestrator.providers.base import (
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
    assert set(DecisionRequest.model_fields) == {"model", "question", "options"}


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


def test_failed_call_is_still_recorded() -> None:
    fake = FakeDecisionProvider(fail_with="boom")
    with pytest.raises(ProviderCallError):
        fake.decide(DecisionRequest(model="m", question="q?", options=("a", "b")))
    assert len(fake.requests) == 1

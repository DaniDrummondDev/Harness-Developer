"""DecisionProvider contract suite (V0.2, expanded in V0.4).

Every decision adapter gets a `Test<Adapter>` subclass providing the fixtures;
the same invariants then hold for the fake and for the real Jev adapter (run
offline against `JevEmulator`, so the suite never needs the network).

Invariants at the adapter boundary:
- identity: `provider` / `model` / `kind` are echoed;
- `choice` in `request.options`; confidence, probability, score in 0..1;
- `probabilities`, when reported, cover exactly the options and sum to ~1;
- `score` only for ordered decisions;
- failures are `ProviderError`s (typed: timeout, invalid response), never vendor
  exceptions, and never echo the question.
Invariant at the Harness boundary (DecisionService): an adapter that returns a
choice outside the options produces FALLBACK_REQUIRED, never a decision.
"""

from __future__ import annotations

import pytest
from jev_emulator import JevEmulator

from orchestrator.config import DecisionThresholds
from orchestrator.core.exceptions import (
    DecisionInvalidResponseError,
    DecisionTimeoutError,
    ProviderError,
)
from orchestrator.decisions.models import FallbackReason
from orchestrator.decisions.service import DecisionService
from orchestrator.providers.base import (
    PROBABILITY_SUM_TOLERANCE,
    DecisionKind,
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    LLMProvider,
)
from orchestrator.providers.fake import FakeDecisionProvider
from orchestrator.providers.jev import JevDecisionProvider
from orchestrator.providers.resolution import ResolvedModel

REQUEST = DecisionRequest(
    model="contract-model",
    question="Which risk level fits this change?",
    options=("LOW", "MEDIUM", "HIGH"),
)
ORDERED = DecisionRequest(
    model="contract-model",
    question="How severe is this issue?",
    options=("low", "medium", "high", "critical"),
    kind=DecisionKind.SEVERITY,
    subject="Login fails for every user after the release",
    ordered=True,
)
ROUTING = DecisionRequest(
    model="contract-model",
    question="Which role should handle this first?",
    options=("architect", "implementer", "reviewer"),
    kind=DecisionKind.ROUTING,
    subject="Add a CSV export to the reports page",
)


class DecisionProviderContract:
    @pytest.fixture
    def provider(self) -> DecisionProvider:
        raise NotImplementedError

    @pytest.fixture
    def failing_provider(self) -> DecisionProvider:
        """An instance of the same adapter whose calls fail."""
        raise NotImplementedError

    @pytest.fixture
    def timeout_provider(self) -> DecisionProvider:
        """An instance whose calls time out."""
        raise NotImplementedError

    @pytest.fixture
    def malformed_provider(self) -> DecisionProvider:
        """An instance whose vendor answers are malformed."""
        raise NotImplementedError

    @pytest.fixture
    def invalid_choice_provider(self) -> DecisionProvider:
        """An instance whose vendor picks something that is not an option."""
        raise NotImplementedError

    # --- shape / identity ------------------------------------------------------------------

    def test_satisfies_decision_contract(self, provider: DecisionProvider) -> None:
        assert isinstance(provider, DecisionProvider)
        assert isinstance(provider.provider_id, str)
        assert provider.provider_id.strip()

    def test_is_not_an_llm_provider(self, provider: DecisionProvider) -> None:
        assert not isinstance(provider, LLMProvider)

    @pytest.mark.parametrize(
        "request_", [REQUEST, ORDERED, ROUTING], ids=["plain", "ordered", "routing"]
    )
    def test_decide_returns_structured_result(
        self, provider: DecisionProvider, request_: DecisionRequest
    ) -> None:
        result = provider.decide(request_)

        assert isinstance(result, DecisionResult)
        assert result.provider == provider.provider_id
        assert result.model == request_.model
        assert result.kind is request_.kind
        assert result.choice in request_.options
        assert 0.0 <= result.confidence <= 1.0
        if result.probability is not None:
            assert 0.0 <= result.probability <= 1.0
        if result.probabilities:
            assert set(result.probabilities) == set(request_.options)
            assert abs(sum(result.probabilities.values()) - 1) <= PROBABILITY_SUM_TOLERANCE
            if result.probability is not None:
                assert result.probability == result.probabilities[result.choice]

    def test_score_only_for_ordered_decisions(self, provider: DecisionProvider) -> None:
        assert provider.decide(REQUEST).score is None
        ordered = provider.decide(ORDERED)
        assert ordered.score is not None
        assert 0.0 <= ordered.score <= 1.0

    # --- failures ------------------------------------------------------------------------------

    def test_failure_is_a_provider_error(self, failing_provider: DecisionProvider) -> None:
        with pytest.raises(ProviderError) as excinfo:
            failing_provider.decide(REQUEST)
        assert failing_provider.provider_id in str(excinfo.value)
        assert REQUEST.question not in str(excinfo.value)

    def test_timeout_is_typed(self, timeout_provider: DecisionProvider) -> None:
        with pytest.raises(DecisionTimeoutError) as excinfo:
            timeout_provider.decide(REQUEST)
        assert timeout_provider.provider_id in str(excinfo.value)

    def test_malformed_answer_is_typed(self, malformed_provider: DecisionProvider) -> None:
        with pytest.raises(DecisionInvalidResponseError) as excinfo:
            malformed_provider.decide(REQUEST)
        assert REQUEST.question not in str(excinfo.value)

    def test_invalid_choice_never_becomes_a_decision(
        self, invalid_choice_provider: DecisionProvider
    ) -> None:
        """Whether the adapter or the service catches it, the Harness never accepts it."""
        service = DecisionService(
            invalid_choice_provider,
            model=ResolvedModel(alias="decision", provider="x", model_id=REQUEST.model),
            thresholds=DecisionThresholds(minimum_confidence=0.0),
        )
        outcome = service.decide(question=REQUEST.question, options=REQUEST.options)
        assert outcome.fallback_required
        assert outcome.fallback_reason is FallbackReason.INVALID_RESPONSE
        assert outcome.choice is None


class TestFakeDecisionProvider(DecisionProviderContract):
    @pytest.fixture
    def provider(self) -> DecisionProvider:
        return FakeDecisionProvider("fake-decision", confidence=0.8)

    @pytest.fixture
    def failing_provider(self) -> DecisionProvider:
        return FakeDecisionProvider("fake-decision", fail_with="rate limited")

    @pytest.fixture
    def timeout_provider(self) -> DecisionProvider:
        return FakeDecisionProvider(fail_with="timed out", fail_as=DecisionTimeoutError)

    @pytest.fixture
    def malformed_provider(self) -> DecisionProvider:
        return FakeDecisionProvider(fail_with="garbage", fail_as=DecisionInvalidResponseError)

    @pytest.fixture
    def invalid_choice_provider(self) -> DecisionProvider:
        return FakeDecisionProvider(choice="NOT-AN-OPTION")


def _jev(emulator: JevEmulator) -> JevDecisionProvider:
    return JevDecisionProvider(api_key="test-key-not-a-secret", transport=emulator)


class TestJevDecisionProvider(DecisionProviderContract):
    @pytest.fixture
    def provider(self) -> DecisionProvider:
        return _jev(JevEmulator())

    @pytest.fixture
    def failing_provider(self) -> DecisionProvider:
        emulator = JevEmulator()
        emulator.fail_status = (500, {"detail": "internal error"})
        return _jev(emulator)

    @pytest.fixture
    def timeout_provider(self) -> DecisionProvider:
        emulator = JevEmulator()
        emulator.timeout = True
        return _jev(emulator)

    @pytest.fixture
    def malformed_provider(self) -> DecisionProvider:
        emulator = JevEmulator()
        emulator.body = {"unexpected": "shape"}
        return _jev(emulator)

    @pytest.fixture
    def invalid_choice_provider(self) -> DecisionProvider:
        emulator = JevEmulator()
        emulator.answer = {
            "type": "choice",
            "choice": "NOT-AN-OPTION",
            "probabilities": {"LOW": 0.1, "MEDIUM": 0.1, "HIGH": 0.8},
            "confidence": 0.7,
        }
        return _jev(emulator)

"""DecisionProvider contract suite.

Reusable like `LLMProviderContract`: the future Jev/TypeSafe adapter (V0.4)
gets its own `Test<Adapter>` subclass providing the two fixtures.
"""

from __future__ import annotations

import pytest

from orchestrator.core.exceptions import ProviderError
from orchestrator.providers.base import (
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
    LLMProvider,
)
from orchestrator.providers.fake import FakeDecisionProvider

REQUEST = DecisionRequest(
    model="contract-model",
    question="Which risk level fits this change?",
    options=("LOW", "MEDIUM", "HIGH"),
)


class DecisionProviderContract:
    @pytest.fixture
    def provider(self) -> DecisionProvider:
        raise NotImplementedError

    @pytest.fixture
    def failing_provider(self) -> DecisionProvider:
        """An instance of the same adapter whose calls fail."""
        raise NotImplementedError

    def test_satisfies_decision_contract(self, provider: DecisionProvider) -> None:
        assert isinstance(provider, DecisionProvider)
        assert isinstance(provider.provider_id, str)
        assert provider.provider_id.strip()

    def test_is_not_an_llm_provider(self, provider: DecisionProvider) -> None:
        assert not isinstance(provider, LLMProvider)

    def test_decide_returns_structured_result(self, provider: DecisionProvider) -> None:
        result = provider.decide(REQUEST)

        assert isinstance(result, DecisionResult)
        assert result.provider == provider.provider_id
        assert result.model == REQUEST.model
        assert result.choice in REQUEST.options
        assert 0.0 <= result.confidence <= 1.0

    def test_failure_is_a_provider_error(self, failing_provider: DecisionProvider) -> None:
        with pytest.raises(ProviderError) as excinfo:
            failing_provider.decide(REQUEST)
        assert failing_provider.provider_id in str(excinfo.value)
        assert REQUEST.question not in str(excinfo.value)


class TestFakeDecisionProvider(DecisionProviderContract):
    @pytest.fixture
    def provider(self) -> DecisionProvider:
        return FakeDecisionProvider("fake-decision", confidence=0.8)

    @pytest.fixture
    def failing_provider(self) -> DecisionProvider:
        return FakeDecisionProvider("fake-decision", fail_with="rate limited")

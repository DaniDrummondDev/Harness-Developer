"""LLMProvider contract suite.

`LLMProviderContract` is reusable: every adapter (fake today; OpenAI,
Anthropic, NVIDIA later) gets a `Test<Adapter>` subclass that provides the
`provider` and `failing_provider` fixtures. The base class is not collected
by pytest (its name does not start with `Test`).
"""

from __future__ import annotations

import pytest

from orchestrator.core.exceptions import ProviderError
from orchestrator.providers.base import DecisionProvider, LLMProvider, LLMRequest, LLMResult
from orchestrator.providers.fake import FakeLLMProvider


class LLMProviderContract:
    @pytest.fixture
    def provider(self) -> LLMProvider:
        raise NotImplementedError

    @pytest.fixture
    def failing_provider(self) -> LLMProvider:
        """An instance of the same adapter whose calls fail."""
        raise NotImplementedError

    def test_satisfies_llm_contract(self, provider: LLMProvider) -> None:
        assert isinstance(provider, LLMProvider)
        assert isinstance(provider.provider_id, str)
        assert provider.provider_id.strip()

    def test_is_not_a_decision_provider(self, provider: LLMProvider) -> None:
        assert not isinstance(provider, DecisionProvider)

    def test_complete_returns_typed_result_with_identity(self, provider: LLMProvider) -> None:
        result = provider.complete(LLMRequest(model="contract-model", prompt="say hi"))

        assert isinstance(result, LLMResult)
        assert result.provider == provider.provider_id
        assert result.model == "contract-model"
        assert isinstance(result.text, str)

    def test_failure_is_a_provider_error(self, failing_provider: LLMProvider) -> None:
        with pytest.raises(ProviderError) as excinfo:
            failing_provider.complete(LLMRequest(model="contract-model", prompt="secret prompt"))
        # Errors identify the provider but never echo the request content.
        assert failing_provider.provider_id in str(excinfo.value)
        assert "secret prompt" not in str(excinfo.value)


class TestFakeLLMProvider(LLMProviderContract):
    @pytest.fixture
    def provider(self) -> LLMProvider:
        return FakeLLMProvider("fake-llm")

    @pytest.fixture
    def failing_provider(self) -> LLMProvider:
        return FakeLLMProvider("fake-llm", fail_with="upstream unavailable")

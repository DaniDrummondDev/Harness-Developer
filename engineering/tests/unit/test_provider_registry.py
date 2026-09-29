from __future__ import annotations

import pytest

from orchestrator.core.exceptions import (
    ProviderNotFoundError,
    ProviderRegistrationError,
    ProviderTypeMismatchError,
)
from orchestrator.providers.fake import FakeDecisionProvider, FakeLLMProvider
from orchestrator.providers.registry import ProviderRegistry


@pytest.fixture
def registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register_llm(FakeLLMProvider("llm-a"))
    registry.register_decision(FakeDecisionProvider("dec-a"))
    return registry


def test_register_and_resolve_by_contract(registry: ProviderRegistry) -> None:
    assert registry.llm("llm-a").provider_id == "llm-a"
    assert registry.decision("dec-a").provider_id == "dec-a"
    assert registry.provider_ids == {"llm-a", "dec-a"}
    assert "llm-a" in registry
    assert "other" not in registry


def test_resolution_returns_the_registered_instance() -> None:
    registry = ProviderRegistry()
    adapter = FakeLLMProvider("llm-a")
    registry.register_llm(adapter)
    assert registry.llm("llm-a") is adapter


def test_unknown_provider_fails_explicitly(registry: ProviderRegistry) -> None:
    with pytest.raises(ProviderNotFoundError, match=r"'missing' \(registered: dec-a, llm-a\)"):
        registry.llm("missing")
    with pytest.raises(ProviderNotFoundError):
        registry.decision("missing")


def test_empty_registry_reports_none() -> None:
    with pytest.raises(ProviderNotFoundError, match="registered: none"):
        ProviderRegistry().llm("x")


@pytest.mark.parametrize(
    "second",
    [FakeLLMProvider("llm-a"), FakeDecisionProvider("llm-a")],
    ids=["same-contract", "other-contract"],
)
def test_duplicate_registration_is_rejected(
    registry: ProviderRegistry, second: FakeLLMProvider | FakeDecisionProvider
) -> None:
    original = registry.llm("llm-a")
    with pytest.raises(ProviderRegistrationError, match="already registered"):
        if isinstance(second, FakeLLMProvider):
            registry.register_llm(second)
        else:
            registry.register_decision(second)
    assert registry.llm("llm-a") is original  # no silent override


def test_type_mismatch_is_explicit(registry: ProviderRegistry) -> None:
    with pytest.raises(ProviderTypeMismatchError, match="registered as DecisionProvider"):
        registry.llm("dec-a")
    with pytest.raises(ProviderTypeMismatchError, match="registered as LLMProvider"):
        registry.decision("llm-a")


def test_registering_under_the_wrong_contract_is_rejected() -> None:
    registry = ProviderRegistry()
    with pytest.raises(ProviderRegistrationError, match="does not implement LLMProvider"):
        registry.register_llm(FakeDecisionProvider("d"))  # type: ignore[arg-type]
    with pytest.raises(ProviderRegistrationError, match="does not implement DecisionProvider"):
        registry.register_decision(FakeLLMProvider("l"))  # type: ignore[arg-type]
    assert registry.provider_ids == frozenset()


@pytest.mark.parametrize("provider_id", ["", "   "])
def test_blank_provider_id_is_rejected(provider_id: str) -> None:
    with pytest.raises(ProviderRegistrationError, match="non-empty"):
        ProviderRegistry().register_llm(FakeLLMProvider(provider_id))

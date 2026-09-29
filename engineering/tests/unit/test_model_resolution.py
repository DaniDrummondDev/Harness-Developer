"""Model resolution end to end: YAML -> HarnessConfig -> ModelResolver -> registry -> adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from orchestrator.config import HarnessConfig, ModelEntry, ProviderEntry, load_config
from orchestrator.core.exceptions import (
    ConfigValidationError,
    ModelNotFoundError,
    ProviderNotEnabledError,
    ProviderNotFoundError,
    ProviderTypeMismatchError,
)
from orchestrator.providers.base import DecisionRequest, LLMRequest, LLMResult
from orchestrator.providers.fake import FakeDecisionProvider, FakeLLMProvider
from orchestrator.providers.registry import ProviderRegistry
from orchestrator.providers.resolution import ModelResolver, ResolvedModel

WriteConfig = Callable[[str, str], Path]

PROVIDERS_YAML = """
    version: 1
    providers:
      alpha: {kind: fake, enabled: true}
      beta: {kind: fake, enabled: true}
      judge: {kind: fake, enabled: true}
      dormant: {kind: fake, enabled: false}
"""


@pytest.fixture
def registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register_llm(FakeLLMProvider("alpha"))
    registry.register_llm(FakeLLMProvider("beta"))
    registry.register_decision(FakeDecisionProvider("judge", confidence=0.9))
    return registry


@pytest.fixture
def config(harness_root: Path, write_config: WriteConfig) -> HarnessConfig:
    write_config("providers.yaml", PROVIDERS_YAML)
    write_config("models.yaml", """
        version: 1
        models:
          strong_reasoning: {provider: alpha, model_id: vendor-model-large}
          classifier: {provider: judge, model_id: judge-v1}
          sleeping: {provider: dormant, model_id: z}
          unregistered: {provider: beta, model_id: b}
    """)
    return load_config(harness_root)


def resolver_for(config: HarnessConfig, registry: ProviderRegistry) -> ModelResolver:
    return ModelResolver(models=config.models, providers=config.providers, registry=registry)


def core_step(resolver: ModelResolver, alias: str, prompt: str) -> LLMResult:
    """Stands in for core code: it knows a logical alias, never a vendor or model name."""
    provider, model = resolver.llm(alias)
    return provider.complete(LLMRequest(model=model.model_id, prompt=prompt))


# --- resolution ---------------------------------------------------------------------


def test_alias_resolves_to_provider_and_provider_model_id(
    config: HarnessConfig, registry: ProviderRegistry
) -> None:
    assert resolver_for(config, registry).resolve("strong_reasoning") == ResolvedModel(
        alias="strong_reasoning", provider="alpha", model_id="vendor-model-large"
    )


def test_llm_alias_calls_the_configured_adapter(
    config: HarnessConfig, registry: ProviderRegistry
) -> None:
    result = core_step(resolver_for(config, registry), "strong_reasoning", "design X")
    assert result == LLMResult(
        provider="alpha", model="vendor-model-large", text="[alpha/vendor-model-large] design X"
    )


def test_decision_alias_calls_the_configured_adapter(
    config: HarnessConfig, registry: ProviderRegistry
) -> None:
    provider, model = resolver_for(config, registry).decision("classifier")
    result = provider.decide(
        DecisionRequest(model=model.model_id, question="severity?", options=("low", "high"))
    )
    assert (result.provider, result.model, result.choice, result.confidence) == (
        "judge", "judge-v1", "low", 0.9
    )


def test_switching_provider_and_model_needs_only_configuration(
    harness_root: Path, write_config: WriteConfig, registry: ProviderRegistry
) -> None:
    write_config("providers.yaml", PROVIDERS_YAML)
    results = []
    for provider, model_id in [("alpha", "model-1"), ("beta", "model-2")]:
        write_config("models.yaml", f"""
            version: 1
            models:
              strong_reasoning: {{provider: {provider}, model_id: {model_id}}}
        """)
        config = load_config(harness_root)
        results.append(core_step(resolver_for(config, registry), "strong_reasoning", "same"))

    assert [(r.provider, r.model) for r in results] == [("alpha", "model-1"), ("beta", "model-2")]


def test_resolution_does_not_depend_on_cwd(
    config: HarnessConfig, registry: ProviderRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    assert resolver_for(config, registry).resolve("classifier").provider == "judge"


# --- failures -------------------------------------------------------------------------


def test_unknown_model_fails_explicitly(config: HarnessConfig, registry: ProviderRegistry) -> None:
    with pytest.raises(ModelNotFoundError, match=r"model 'nope' is not declared.*classifier"):
        resolver_for(config, registry).llm("nope")


def test_disabled_provider_fails_closed(config: HarnessConfig, registry: ProviderRegistry) -> None:
    with pytest.raises(ProviderNotEnabledError, match="'dormant', which is disabled"):
        resolver_for(config, registry).resolve("sleeping")


def test_enabled_provider_without_adapter_fails(
    config: HarnessConfig, registry: ProviderRegistry
) -> None:
    resolver = ModelResolver(
        models=config.models, providers=config.providers, registry=ProviderRegistry()
    )
    with pytest.raises(ProviderNotFoundError, match="no adapter registered for provider 'alpha'"):
        resolver.llm("strong_reasoning")


def test_wrong_contract_for_alias_fails(config: HarnessConfig, registry: ProviderRegistry) -> None:
    resolver = resolver_for(config, registry)
    with pytest.raises(ProviderTypeMismatchError):
        resolver.llm("classifier")
    with pytest.raises(ProviderTypeMismatchError):
        resolver.decision("strong_reasoning")


def test_undeclared_provider_is_rejected_by_resolver(registry: ProviderRegistry) -> None:
    """load_config already rejects this; the resolver still guards unvalidated mappings."""
    resolver = ModelResolver(
        models={"m": ModelEntry(provider="ghost", model_id="x")},
        providers={"alpha": ProviderEntry(kind="fake", enabled=True)},
        registry=registry,
    )
    with pytest.raises(ProviderNotFoundError, match="'ghost', which is not declared"):
        resolver.resolve("m")


def test_shipped_configuration_needs_no_adapter(harness_root: Path) -> None:
    """Shipped config: all providers disabled, no models -> nothing resolvable, nothing called."""
    config = load_config(harness_root)
    resolver = resolver_for(config, ProviderRegistry())
    assert config.models == {}
    with pytest.raises(ModelNotFoundError, match="declared: none"):
        resolver.resolve("anything")


# --- providers.yaml / models.yaml validation -------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("models.yaml", "version: 1\nmodels: {m: {provider: openai}}\n", "model_id"),
        ("models.yaml", "version: 1\nmodels: {m: {provider: openai, model_id: '  '}}\n",
         "model_id"),
        ("models.yaml", "version: 1\nmodels: {m: {provider: openai, model_id: x, temp: 1}}\n",
         "temp"),
        ("models.yaml", "version: 1\nmodels: {Bad: {provider: openai, model_id: x}}\n", "Bad"),
        ("models.yaml", "version: 1\nmodels: {m: {provider: nope, model_id: x}}\n",
         "provider 'nope' is not declared"),
        ("providers.yaml", "version: 1\nproviders: {openai: {kind: openai, api_key: sk-x}}\n",
         "api_key"),
        ("providers.yaml", "version: 1\nproviders: {openai: {enabled: true}}\n", "kind"),
    ],
)
def test_invalid_provider_or_model_config_fails(
    harness_root: Path, write_config: WriteConfig, filename: str, content: str, expected: str
) -> None:
    write_config(filename, content)
    with pytest.raises(ConfigValidationError, match=expected):
        load_config(harness_root)

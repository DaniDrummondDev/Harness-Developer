"""Model resolution: logical model alias -> provider -> provider model id -> adapter.

    models.yaml    strong_reasoning: {provider: openai, model_id: <vendor model name>}
    providers.yaml openai: {kind: openai, enabled: true}

    ModelResolver.resolve("strong_reasoning")
        -> ResolvedModel(alias="strong_reasoning", provider="openai", model_id="<vendor name>")
    ModelResolver.llm("strong_reasoning")
        -> (registry.llm("openai"), ResolvedModel(...))

Callers depend only on the alias. Switching an alias to another provider or
vendor model is a models.yaml change; no calling code changes (roadmap V0.2
exit criterion).

Failure order (first failing step wins, each with its own error):

    alias not in models.yaml          -> ModelNotFoundError
    provider not in providers.yaml    -> ProviderNotFoundError   (normally caught by load_config)
    provider `enabled: false`         -> ProviderNotEnabledError (fail closed)
    no adapter in the registry        -> ProviderNotFoundError
    adapter implements other contract -> ProviderTypeMismatchError

The resolver consumes already-validated configuration objects (from
`orchestrator.config`), never YAML files, and does not build adapters:
registering adapters is the caller's composition step.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from orchestrator.config import ModelEntry, ProviderEntry
from orchestrator.core.exceptions import (
    ModelNotFoundError,
    ProviderNotEnabledError,
    ProviderNotFoundError,
)
from orchestrator.providers.base import DecisionProvider, LLMProvider
from orchestrator.providers.registry import ProviderRegistry


class ResolvedModel(BaseModel):
    """Where a logical model alias points. `model_id` is what the adapter sends
    to the vendor; `alias` is what the rest of the Harness refers to."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    alias: str
    provider: str
    model_id: str


class ModelResolver:
    def __init__(
        self,
        *,
        models: Mapping[str, ModelEntry],
        providers: Mapping[str, ProviderEntry],
        registry: ProviderRegistry,
    ) -> None:
        self._models = models
        self._providers = providers
        self._registry = registry

    def resolve(self, alias: str) -> ResolvedModel:
        """Configuration-only resolution (no adapter lookup)."""
        entry = self._models.get(alias)
        if entry is None:
            declared = ", ".join(sorted(self._models)) or "none"
            raise ModelNotFoundError(
                f"model '{alias}' is not declared in models.yaml (declared: {declared})"
            )
        provider = self._providers.get(entry.provider)
        if provider is None:
            raise ProviderNotFoundError(
                f"model '{alias}' references provider '{entry.provider}', "
                "which is not declared in providers.yaml"
            )
        if not provider.enabled:
            raise ProviderNotEnabledError(
                f"model '{alias}' uses provider '{entry.provider}', "
                "which is disabled in providers.yaml"
            )
        return ResolvedModel(alias=alias, provider=entry.provider, model_id=entry.model_id)

    def llm(self, alias: str) -> tuple[LLMProvider, ResolvedModel]:
        """Adapter + model for a generative call: build `LLMRequest(model=model.model_id)`."""
        model = self.resolve(alias)
        return self._registry.llm(model.provider), model

    def decision(self, alias: str) -> tuple[DecisionProvider, ResolvedModel]:
        """Adapter + model for a decision: build `DecisionRequest(model=model.model_id)`."""
        model = self.resolve(alias)
        return self._registry.decision(model.provider), model

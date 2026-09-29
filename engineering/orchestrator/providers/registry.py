"""Runtime registry: provider id -> adapter instance, per contract.

    register_llm(adapter)       adapter.provider_id -> LLMProvider
    register_decision(adapter)  adapter.provider_id -> DecisionProvider
    llm(provider_id)            -> LLMProvider       | NotFound | TypeMismatch
    decision(provider_id)       -> DecisionProvider  | NotFound | TypeMismatch

Semantics:
- a provider id is unique across both contracts; registering it twice raises
  `ProviderRegistrationError` (no silent override);
- the registry holds adapters, not configuration: it never reads YAML and
  knows nothing about models, roles, requests or the CLI. Which providers are
  declared/enabled is `ModelResolver`'s job (providers/resolution.py);
- lookups are typed: asking for an LLM under a decision provider's id raises
  `ProviderTypeMismatchError` instead of returning the wrong object.
"""

from __future__ import annotations

from typing import NoReturn

from orchestrator.core.exceptions import (
    ProviderNotFoundError,
    ProviderRegistrationError,
    ProviderTypeMismatchError,
)
from orchestrator.providers.base import DecisionProvider, LLMProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._llm: dict[str, LLMProvider] = {}
        self._decision: dict[str, DecisionProvider] = {}

    # --- registration ----------------------------------------------------------------

    def register_llm(self, provider: LLMProvider) -> None:
        if not isinstance(provider, LLMProvider):
            raise ProviderRegistrationError(
                f"{type(provider).__name__} does not implement LLMProvider"
            )
        self._llm[self._new_id(provider.provider_id)] = provider

    def register_decision(self, provider: DecisionProvider) -> None:
        if not isinstance(provider, DecisionProvider):
            raise ProviderRegistrationError(
                f"{type(provider).__name__} does not implement DecisionProvider"
            )
        self._decision[self._new_id(provider.provider_id)] = provider

    def _new_id(self, provider_id: str) -> str:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ProviderRegistrationError("provider_id must be a non-empty string")
        if provider_id in self:
            raise ProviderRegistrationError(f"provider '{provider_id}' is already registered")
        return provider_id

    # --- lookup ----------------------------------------------------------------------

    def __contains__(self, provider_id: object) -> bool:
        return provider_id in self._llm or provider_id in self._decision

    @property
    def provider_ids(self) -> frozenset[str]:
        return frozenset(self._llm) | frozenset(self._decision)

    def llm(self, provider_id: str) -> LLMProvider:
        if provider_id in self._llm:
            return self._llm[provider_id]
        self._raise_missing(provider_id, wanted="LLMProvider", other="DecisionProvider")

    def decision(self, provider_id: str) -> DecisionProvider:
        if provider_id in self._decision:
            return self._decision[provider_id]
        self._raise_missing(provider_id, wanted="DecisionProvider", other="LLMProvider")

    def _raise_missing(self, provider_id: str, *, wanted: str, other: str) -> NoReturn:
        if provider_id in self:
            raise ProviderTypeMismatchError(
                f"provider '{provider_id}' is registered as {other}, not {wanted}"
            )
        registered = ", ".join(sorted(self.provider_ids)) or "none"
        raise ProviderNotFoundError(
            f"no adapter registered for provider '{provider_id}' (registered: {registered})"
        )

"""Provider contracts (V0.2): what the Harness needs from an LLM or a decision provider.

Two small, separate contracts — deliberately NOT one "AI provider" interface:

    LLMProvider       generative inference:  LLMRequest      -> LLMResult
    DecisionProvider  structured decision:   DecisionRequest -> DecisionResult

Contracts are structural (`typing.Protocol`): an adapter satisfies one by
shape, without inheriting from Harness classes, so vendor adapters stay
isolated in their own modules. The core depends only on this module.

Rules every adapter must follow (checked by tests/contract/):

1. `provider_id` is the key the provider is declared under in providers.yaml
   (e.g. "openai"), and results echo it in `provider`;
2. results echo `request.model` in `model` (the provider's model identifier);
3. a decision's `choice` is one of `request.options`;
4. every failure is raised as a `ProviderError` subclass (normally
   `ProviderCallError`); vendor exceptions never escape the adapter;
5. no network, SDK or credential is touched at construction time in tests.

Intentionally absent until a version needs them: system prompts, sampling
parameters, streaming, tool calls, token/cost accounting, reasoning traces,
retries, timeouts, fallback (V2 / V0.4 / V15).
"""

from __future__ import annotations

from typing import Annotated, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- LLM ---------------------------------------------------------------------------


class LLMRequest(_Contract):
    """A single generative call. `model` is the provider's model identifier
    (`model_id` in models.yaml), not the logical alias."""

    model: NonEmptyStr
    prompt: NonEmptyStr


class LLMResult(_Contract):
    """Output of a generative call, tagged with who produced it (auditability)."""

    provider: NonEmptyStr
    model: NonEmptyStr
    text: str


@runtime_checkable
class LLMProvider(Protocol):
    """Generative inference provider (future adapters: OpenAI, Anthropic, NVIDIA)."""

    @property
    def provider_id(self) -> str: ...

    def complete(self, request: LLMRequest) -> LLMResult:
        """Run one completion. Raises `ProviderError` on failure."""
        ...


# --- Decision ----------------------------------------------------------------------


class DecisionRequest(_Contract):
    """Choose exactly one of `options` for `question` (e.g. classification, routing)."""

    model: NonEmptyStr
    question: NonEmptyStr
    options: tuple[NonEmptyStr, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def _options_unique(self) -> Self:
        if len(set(self.options)) != len(self.options):
            raise ValueError("decision options must be unique")
        return self


class DecisionResult(_Contract):
    """A probabilistic decision. `confidence` is the provider's probability for
    `choice`; it is never treated as deterministic (see docs, decision layer)."""

    provider: NonEmptyStr
    model: NonEmptyStr
    choice: NonEmptyStr
    confidence: Confidence


@runtime_checkable
class DecisionProvider(Protocol):
    """Structured/probabilistic decision provider (future adapter: Jev / TypeSafe)."""

    @property
    def provider_id(self) -> str: ...

    def decide(self, request: DecisionRequest) -> DecisionResult:
        """Return a decision whose `choice` is in `request.options`.
        Raises `ProviderError` on failure."""
        ...

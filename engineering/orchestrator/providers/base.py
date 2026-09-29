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

V0.4 evolved the decision contract additively (typed kind, subject, ordered
options, probability/score metadata); old call sites are unchanged. Timeouts
live in adapters, fallback signalling in `orchestrator.decisions`.

Intentionally absent until a version needs them: system prompts, sampling
parameters, streaming, tool calls, cost accounting, reasoning traces,
retries (V2 / V15).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Any value in 0..1: confidence, probability, normalized score.
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
# Vendors round probabilities; a distribution may sum to 1 +/- this.
PROBABILITY_SUM_TOLERANCE: Final = 0.02


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


class DecisionKind(StrEnum):
    """What a decision is used for (telemetry/audit label; V0.4 first uses).

    The kind never changes how a provider decides: the options, `ordered` and the
    question carry the meaning. Option vocabularies (bug/feature, low/high...) are
    the caller's data, not Harness enums.
    """

    CLASSIFICATION = "classification"
    ROUTING = "routing"
    SEVERITY = "severity"
    CONTEXT_RELEVANCE = "context_relevance"


class DecisionRequest(_Contract):
    """Choose exactly one of `options` for `question` (e.g. classification, routing).

    V0.4 additions (all optional, so V0.2 requests stay valid):
    - `kind`: audit label, see `DecisionKind`;
    - `subject`: the content being judged (e.g. the task text). Kept apart from
      `question` so the instruction stays stable while the subject varies;
    - `ordered`: options run from lowest to highest (e.g. severity). Enables `score`;
    - `descriptions`: optional rubric per option, keyed by option.
    """

    model: NonEmptyStr
    question: NonEmptyStr
    options: tuple[NonEmptyStr, ...] = Field(min_length=2)
    kind: DecisionKind = DecisionKind.CLASSIFICATION
    subject: NonEmptyStr | None = None
    ordered: bool = False
    descriptions: dict[str, NonEmptyStr] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _options_unique(self) -> Self:
        if len(set(self.options)) != len(self.options):
            raise ValueError("decision options must be unique")
        unknown = sorted(set(self.descriptions) - set(self.options))
        if unknown:
            raise ValueError(f"descriptions reference unknown options: {unknown}")
        return self


class DecisionResult(_Contract):
    """A probabilistic decision, tagged with who produced it. Never deterministic:
    even `confidence == 1.0` is a model's belief, not a proof (see docs/architecture.md).

    Metrics (each in 0..1, each with its own meaning):
    - `confidence`  how concentrated the provider's distribution is (Jev: derived
                    from `probabilities`; 1 = all mass on one option). Required;
    - `probability` the provider's probability for `choice`. None = not reported;
    - `probabilities` full distribution, option -> probability (sums to ~1). Empty =
                    not reported;
    - `score`       ordered decisions only: probability-weighted position on the
                    options scale, normalized so 0 = first option, 1 = last option.
                    None = not an ordered decision or not reported.

    `model` echoes `request.model` (the configured model id or alias);
    `resolved_model` is the exact version the vendor reports it used, if any.
    """

    provider: NonEmptyStr
    model: NonEmptyStr
    choice: NonEmptyStr
    confidence: Confidence
    kind: DecisionKind = DecisionKind.CLASSIFICATION
    probability: Confidence | None = None
    probabilities: dict[str, Confidence] = Field(default_factory=dict)
    score: Confidence | None = None
    resolved_model: NonEmptyStr | None = None
    input_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _distribution_consistent(self) -> Self:
        if self.probabilities:
            if self.choice not in self.probabilities:
                raise ValueError("choice is missing from probabilities")
            total = sum(self.probabilities.values())
            if abs(total - 1.0) > PROBABILITY_SUM_TOLERANCE:
                raise ValueError(f"probabilities must sum to 1 (got {total:.4f})")
        return self


@runtime_checkable
class DecisionProvider(Protocol):
    """Structured/probabilistic decision provider (V0.4 adapter: providers/jev.py)."""

    @property
    def provider_id(self) -> str: ...

    def decide(self, request: DecisionRequest) -> DecisionResult:
        """Return a decision whose `choice` is in `request.options`.
        Raises `ProviderError` on failure."""
        ...

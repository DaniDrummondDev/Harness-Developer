"""Deterministic fake adapters, for tests only (no network, SDK or credentials).

They are real implementations of the contracts in `providers/base.py`, so the
same contract tests (tests/contract/) run against them and, later, against
every concrete vendor adapter. Nothing in the Harness registers them
automatically; tests (or a future offline mode) register them explicitly.

Behaviour:
- `FakeLLMProvider.complete` returns `"[<provider>/<model>] <prompt>"`;
- `FakeDecisionProvider.decide` picks `request.options[0]` (or a fixed `choice`)
  with a fixed confidence/score;
- `fail_with="<reason>"` makes every call fail the way a real adapter must:
  a vendor-level exception is caught at the adapter boundary and re-raised
  as `ProviderCallError` or the subclass given in `fail_as` (the pattern
  concrete adapters must follow);
- every received request is recorded in `.requests` for assertions.
"""

from __future__ import annotations

from orchestrator.core.exceptions import ProviderCallError
from orchestrator.providers.base import (
    DecisionRequest,
    DecisionResult,
    LLMRequest,
    LLMResult,
)


class FakeVendorError(Exception):
    """Stands in for a vendor SDK/HTTP exception; never leaves a fake adapter."""


class _FakeAdapter:
    def __init__(
        self,
        provider_id: str,
        *,
        fail_with: str | None = None,
        fail_as: type[ProviderCallError] = ProviderCallError,
    ) -> None:
        self._provider_id = provider_id
        self._fail_with = fail_with
        self._fail_as = fail_as

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def _vendor_call(self) -> None:
        if self._fail_with is not None:
            raise FakeVendorError(self._fail_with)

    def _call(self) -> None:
        """Error translation boundary: vendor exception -> ProviderCallError."""
        try:
            self._vendor_call()
        except FakeVendorError as exc:
            raise self._fail_as(self._provider_id, str(exc)) from exc


class FakeLLMProvider(_FakeAdapter):
    def __init__(self, provider_id: str = "fake-llm", *, fail_with: str | None = None) -> None:
        super().__init__(provider_id, fail_with=fail_with)
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        self._call()
        return LLMResult(
            provider=self.provider_id,
            model=request.model,
            text=f"[{self.provider_id}/{request.model}] {request.prompt}",
        )


class FakeDecisionProvider(_FakeAdapter):
    """Deterministic decision adapter.

    - `choice`: fixed answer (default: `request.options[0]`). Passing a value that
      is not an option simulates a provider breaking the contract, which the
      decision service must reject (V0.4 boundary validation);
    - `confidence` / `score`: fixed metrics. For an ordered request without an
      explicit `score`, the fake reports the choice's position (index / (n - 1));
    - `fail_as`: the `ProviderCallError` subclass raised with `fail_with`, e.g.
      `DecisionTimeoutError` to simulate a timeout.
    """

    def __init__(
        self,
        provider_id: str = "fake-decision",
        *,
        confidence: float = 1.0,
        choice: str | None = None,
        score: float | None = None,
        fail_with: str | None = None,
        fail_as: type[ProviderCallError] = ProviderCallError,
    ) -> None:
        super().__init__(provider_id, fail_with=fail_with, fail_as=fail_as)
        self._confidence = confidence
        self._choice = choice
        self._score = score
        self.requests: list[DecisionRequest] = []

    def decide(self, request: DecisionRequest) -> DecisionResult:
        self.requests.append(request)
        self._call()
        choice = self._choice if self._choice is not None else request.options[0]
        score = self._score
        if score is None and request.ordered and choice in request.options:
            score = request.options.index(choice) / (len(request.options) - 1)
        return DecisionResult(
            provider=self.provider_id,
            model=request.model,
            choice=choice,
            confidence=self._confidence,
            kind=request.kind,
            score=score,
        )

"""`DecisionService`: the single entry point for probabilistic decisions (V0.4).

    caller (CLI today; Context Engine V1.x, Decision Policy Engine V5 later)
        -> DecisionService.decide(question=..., options=..., kind=..., subject=...)
             1. build a typed DecisionRequest (model id from models.yaml)
                                                         -> InvalidDecisionRequestError
             2. DecisionProvider.decide (Jev adapter or fake)
             3. boundary validation: choice in options, identity echoed,
                distribution over exactly the options, score only if ordered
             4. threshold: confidence < minimum_confidence -> FALLBACK_REQUIRED
             5. telemetry: one JSON log line + attached to the outcome
        <- DecisionOutcome (DECIDED | FALLBACK_REQUIRED + reason)

Step 3 exists because the Harness never trusts a provider to respect the
contract (the adapter validates too, the service is the guarantee for every
adapter). Fallbacks are only signalled, never executed (see decisions/models.py).

`open_decisions(config)` is the composition step: decisions.yaml (alias,
thresholds) -> ModelResolver (alias -> provider -> model id, enabled check)
-> adapter built from providers.yaml + environment -> ProviderRegistry ->
DecisionService. It is the only place that reads the decision API key.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic import ValidationError as PydanticValidationError

from orchestrator.config import DecisionThresholds, HarnessConfig, ProviderEntry
from orchestrator.core.exceptions import (
    DecisionAuthenticationError,
    DecisionInvalidResponseError,
    DecisionTimeoutError,
    DecisionUnavailableError,
    InvalidDecisionRequestError,
    ProviderCallError,
    ProviderError,
    ProviderNotEnabledError,
    ProviderNotFoundError,
)
from orchestrator.decisions.models import (
    DecisionHealth,
    DecisionOutcome,
    DecisionStatus,
    DecisionTelemetry,
    FallbackReason,
    HealthStatus,
)
from orchestrator.providers import jev
from orchestrator.providers.base import (
    DecisionKind,
    DecisionProvider,
    DecisionRequest,
    DecisionResult,
)
from orchestrator.providers.registry import ProviderRegistry
from orchestrator.providers.resolution import ModelResolver, ResolvedModel

TELEMETRY_LOGGER = "orchestrator.decisions.telemetry"
telemetry_logger = logging.getLogger(TELEMETRY_LOGGER)

# Provider errors that mean "ask another layer"; everything else is raised.
_FALLBACK_ERRORS: tuple[tuple[type[ProviderCallError], FallbackReason], ...] = (
    (DecisionTimeoutError, FallbackReason.TIMEOUT),  # before its parent class
    (DecisionUnavailableError, FallbackReason.UNAVAILABLE),
    (DecisionInvalidResponseError, FallbackReason.INVALID_RESPONSE),
)


@runtime_checkable
class SupportsPing(Protocol):
    """Optional adapter capability: an authenticated round trip without inference."""

    def ping(self) -> None: ...


def contract_violations(request: DecisionRequest, result: DecisionResult,
                        provider_id: str) -> list[str]:
    """Harness-side invariants every decision must satisfy, whatever the adapter."""
    problems = []
    if result.choice not in request.options:
        problems.append("choice is not one of the requested options")
    if result.provider != provider_id:
        problems.append("result provider does not match the adapter")
    if result.model != request.model:
        problems.append("result model does not echo the requested model")
    if result.kind is not request.kind:
        problems.append("result kind does not echo the requested kind")
    if result.probabilities and set(result.probabilities) != set(request.options):
        problems.append("probabilities do not cover exactly the requested options")
    if result.score is not None and not request.ordered:
        problems.append("score reported for an unordered decision")
    return problems


def _problems(exc: PydanticValidationError) -> str:
    # Locations and messages only: inputs (question/subject) are never echoed.
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'value'}: {err['msg']}" for err in exc.errors()
    )


class DecisionService:
    def __init__(
        self,
        provider: DecisionProvider,
        *,
        model: ResolvedModel,
        thresholds: DecisionThresholds,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._provider = provider
        self._model = model
        self._thresholds = thresholds
        self._clock = clock
        self._now = now

    @property
    def provider_id(self) -> str:
        return self._provider.provider_id

    @property
    def model(self) -> ResolvedModel:
        return self._model

    @property
    def thresholds(self) -> DecisionThresholds:
        return self._thresholds

    # --- decisions ---------------------------------------------------------------------------

    def decide(
        self,
        *,
        question: str,
        options: tuple[str, ...] | list[str],
        kind: DecisionKind = DecisionKind.CLASSIFICATION,
        subject: str | None = None,
        ordered: bool = False,
        descriptions: Mapping[str, str] | None = None,
    ) -> DecisionOutcome:
        """Make one decision. Returns an outcome for success, low confidence, provider
        unavailability/timeouts and invalid responses. Raises for invalid input
        (InvalidDecisionRequestError), rejected credentials (DecisionAuthenticationError)
        and other provider errors (ProviderCallError)."""
        try:
            request = DecisionRequest(
                model=self._model.model_id,
                question=question,
                options=tuple(options),
                kind=kind,
                subject=subject,
                ordered=ordered,
                descriptions=dict(descriptions or {}),
            )
        except PydanticValidationError as exc:
            raise InvalidDecisionRequestError(
                f"invalid decision request: {_problems(exc)}"
            ) from exc

        started = self._clock()
        try:
            result = self._provider.decide(request)
        except ProviderCallError as exc:
            reason = next((r for cls, r in _FALLBACK_ERRORS if isinstance(exc, cls)), None)
            if reason is None:  # auth, 422, unexpected status: must be fixed, not routed
                self._emit(request, started, status=DecisionStatus.ERROR, error=exc)
                raise
            return self._fallback(request, started, reason, detail=str(exc), error=exc)

        violations = contract_violations(request, result, self._provider.provider_id)
        if violations:
            detail = f"provider '{self.provider_id}' broke the decision contract: " + "; ".join(
                violations
            )
            error = DecisionInvalidResponseError(self.provider_id, "; ".join(violations))
            return self._fallback(request, started, FallbackReason.INVALID_RESPONSE,
                                  detail=detail, error=error)

        minimum = self._thresholds.minimum_confidence
        if result.confidence < minimum:
            return self._fallback(
                request, started, FallbackReason.LOW_CONFIDENCE,
                detail=f"confidence {result.confidence:.2f} is below the minimum {minimum:.2f}",
                result=result,
            )
        telemetry = self._emit(request, started, status=DecisionStatus.DECIDED, result=result)
        return DecisionOutcome(
            status=DecisionStatus.DECIDED, kind=request.kind, result=result, telemetry=telemetry
        )

    def _fallback(
        self,
        request: DecisionRequest,
        started: float,
        reason: FallbackReason,
        *,
        detail: str,
        result: DecisionResult | None = None,
        error: ProviderError | None = None,
    ) -> DecisionOutcome:
        telemetry = self._emit(request, started, status=DecisionStatus.FALLBACK_REQUIRED,
                               reason=reason, result=result, error=error)
        return DecisionOutcome(
            status=DecisionStatus.FALLBACK_REQUIRED,
            kind=request.kind,
            result=result,
            fallback_reason=reason,
            detail=detail,
            telemetry=telemetry,
        )

    def _emit(
        self,
        request: DecisionRequest,
        started: float,
        *,
        status: DecisionStatus,
        reason: FallbackReason | None = None,
        result: DecisionResult | None = None,
        error: ProviderError | None = None,
    ) -> DecisionTelemetry:
        telemetry = DecisionTelemetry(
            timestamp=self._now(),
            provider=self.provider_id,
            model_alias=self._model.alias,
            model=request.model,
            resolved_model=result.resolved_model if result else None,
            kind=request.kind,
            option_count=len(request.options),
            status=status,
            choice=result.choice if result else None,
            confidence=result.confidence if result else None,
            probability=result.probability if result else None,
            score=result.score if result else None,
            minimum_confidence=self._thresholds.minimum_confidence,
            fallback_required=status is DecisionStatus.FALLBACK_REQUIRED,
            fallback_reason=reason,
            error_category=type(error).__name__ if error else None,
            duration_ms=max(0.0, (self._clock() - started) * 1000),
            input_tokens=result.input_tokens if result else None,
        )
        telemetry_logger.info("decision %s", telemetry.model_dump_json())
        return telemetry

    # --- connectivity --------------------------------------------------------------------------

    def health(self) -> DecisionHealth:
        """Connectivity/credential check without inference. Never raises for
        provider errors; maps them to a status."""

        def health(status: HealthStatus, detail: str) -> DecisionHealth:
            return DecisionHealth(
                provider=self.provider_id, status=status, detail=detail, checked_at=self._now()
            )

        if not isinstance(self._provider, SupportsPing):
            return health(HealthStatus.HEALTHY, "adapter has no connectivity check (offline)")
        try:
            self._provider.ping()
        except DecisionAuthenticationError as exc:
            return health(HealthStatus.MISCONFIGURED, str(exc))
        except ProviderCallError as exc:
            return health(HealthStatus.UNAVAILABLE, str(exc))
        return health(
            HealthStatus.HEALTHY,
            f"provider '{self.provider_id}' reachable, credentials accepted "
            f"(model alias '{self._model.alias}' -> {self._model.model_id})",
        )


# --- composition -------------------------------------------------------------------------------


def build_decision_adapter(
    provider_id: str,
    entry: ProviderEntry,
    environ: Mapping[str, str] | None = None,
    *,
    transport: jev.Transport | None = None,
) -> DecisionProvider:
    """providers.yaml entry + environment -> concrete DecisionProvider adapter.
    Only `kind: jev` has a decision adapter in V0.4."""
    if entry.kind != "jev":
        raise ProviderNotFoundError(
            f"provider '{provider_id}' has kind '{entry.kind}', which has no decision adapter "
            "(available: jev)"
        )
    env = os.environ if environ is None else environ
    key_env = entry.api_key_env or jev.DEFAULT_API_KEY_ENV
    api_key = env.get(key_env, "").strip()
    if not api_key:
        raise DecisionAuthenticationError(
            provider_id, f"${key_env} is not set; export the TypeSafe API key to use Jev"
        )
    return jev.JevDecisionProvider(
        api_key=api_key,
        provider_id=provider_id,
        base_url=entry.base_url or jev.DEFAULT_BASE_URL,
        timeout=entry.timeout_seconds or jev.DEFAULT_TIMEOUT_SECONDS,
        api_key_env=key_env,
        transport=transport,
    )


def open_decisions(
    config: HarnessConfig,
    environ: Mapping[str, str] | None = None,
    *,
    transport: jev.Transport | None = None,
) -> DecisionService:
    """Build the configured decision layer. Fails closed without any network call:
    ProviderNotEnabledError (not configured / provider disabled), ModelNotFoundError,
    ProviderNotFoundError (no adapter for the kind), DecisionAuthenticationError (no key)."""
    section = config.decisions
    if section.model is None or section.thresholds is None:
        raise ProviderNotEnabledError(
            "decisions are not configured (set decisions.model and decisions.thresholds "
            "in decisions.yaml)"
        )
    registry = ProviderRegistry()
    resolver = ModelResolver(models=config.models, providers=config.providers, registry=registry)
    resolved = resolver.resolve(section.model)  # alias declared, provider declared + enabled
    registry.register_decision(
        build_decision_adapter(
            resolved.provider, config.providers[resolved.provider], environ, transport=transport
        )
    )
    provider, model = resolver.decision(section.model)
    return DecisionService(provider, model=model, thresholds=section.thresholds)

"""Typed results of the decision layer: outcome, fallback contract, telemetry, health.

Fallback contract (what a consumer receives, never an automatic fallback call):

    situation                               status              fallback_reason   result
    confident, valid decision               DECIDED             -                 yes
    confidence < thresholds.minimum         FALLBACK_REQUIRED   low_confidence    yes (audit)
    provider unreachable / 429 / 5xx        FALLBACK_REQUIRED   unavailable       no
    provider timed out                      FALLBACK_REQUIRED   timeout           no
    malformed body, choice not in options   FALLBACK_REQUIRED   invalid_response  no
    missing/rejected credentials, 422       raised (DecisionAuthenticationError /
                                            ProviderCallError): configuration or request
                                            bugs must be fixed, not silently routed to
                                            another layer.

Telemetry never contains the question, the subject, descriptions or credentials:
only identities, metrics, timing and error categories.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from orchestrator.providers.base import DecisionKind, DecisionResult


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionStatus(StrEnum):
    DECIDED = "decided"
    FALLBACK_REQUIRED = "fallback_required"
    ERROR = "error"  # telemetry only: the call raised (credentials, rejected request)


class FallbackReason(StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"


class DecisionTelemetry(_Frozen):
    """Minimal per-decision record (RF-054 subset). Emitted as one JSON log line on
    the `orchestrator.decisions.telemetry` logger (INFO) and attached to the outcome."""

    timestamp: AwareDatetime
    provider: str
    model_alias: str
    model: str  # model id sent to the provider
    resolved_model: str | None = None  # exact version reported by the provider
    kind: DecisionKind
    option_count: int = Field(ge=2)
    status: DecisionStatus
    choice: str | None = None
    confidence: float | None = None
    probability: float | None = None
    score: float | None = None
    minimum_confidence: float
    fallback_required: bool
    fallback_reason: FallbackReason | None = None
    error_category: str | None = None  # Harness error class name, e.g. DecisionTimeoutError
    duration_ms: float = Field(ge=0)
    input_tokens: int | None = None


class DecisionOutcome(_Frozen):
    """What the decision layer returns for one decision."""

    status: DecisionStatus
    kind: DecisionKind
    result: DecisionResult | None = None
    fallback_reason: FallbackReason | None = None
    detail: str | None = None  # sanitized reason when a fallback is required
    telemetry: DecisionTelemetry

    @property
    def fallback_required(self) -> bool:
        return self.status is DecisionStatus.FALLBACK_REQUIRED

    @property
    def choice(self) -> str | None:
        """The accepted choice; None whenever a fallback is required."""
        return self.result.choice if self.status is DecisionStatus.DECIDED and self.result else None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.status is DecisionStatus.ERROR:
            raise ValueError("ERROR is a telemetry status; errors are raised, not returned")
        if self.status is DecisionStatus.DECIDED:
            if self.result is None or self.fallback_reason is not None:
                raise ValueError("a DECIDED outcome has a result and no fallback reason")
        elif self.fallback_reason is None:
            raise ValueError("a FALLBACK_REQUIRED outcome needs a fallback reason")
        return self


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNAVAILABLE = "unavailable"  # network/service problem: the Harness still works without it
    MISCONFIGURED = "misconfigured"  # credentials rejected: the user must fix configuration


class DecisionHealth(_Frozen):
    provider: str
    status: HealthStatus
    detail: str
    checked_at: datetime

    @property
    def ok(self) -> bool:
        return self.status is HealthStatus.HEALTHY

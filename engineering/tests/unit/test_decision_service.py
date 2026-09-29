"""DecisionService: boundary validation, thresholds, fallback contract, telemetry, health."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from jev_emulator import JevEmulator
from pydantic import ValidationError

from orchestrator.config import DecisionThresholds
from orchestrator.core.exceptions import (
    DecisionAuthenticationError,
    DecisionInvalidResponseError,
    DecisionTimeoutError,
    DecisionUnavailableError,
    InvalidDecisionRequestError,
    ProviderCallError,
)
from orchestrator.decisions.models import (
    DecisionOutcome,
    DecisionStatus,
    FallbackReason,
    HealthStatus,
)
from orchestrator.decisions.service import TELEMETRY_LOGGER, DecisionService
from orchestrator.providers.base import DecisionKind, DecisionProvider, DecisionResult
from orchestrator.providers.fake import FakeDecisionProvider, FakeLLMProvider
from orchestrator.providers.jev import JevDecisionProvider
from orchestrator.providers.resolution import ResolvedModel
from orchestrator.utils.logging import ROOT_LOGGER_NAME

MODEL = ResolvedModel(alias="decision", provider="fake-decision", model_id="judge-v1")
QUESTION = "What kind of engineering work is this?"
SUBJECT = "Fix failing authentication test for user alice"
OPTIONS = ("bug", "feature", "refactor")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


class Clock:
    """Monotonic clock advancing 25 ms per reading (start, end)."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        self.t += 0.025
        return self.t


def service(provider: DecisionProvider, minimum: float = 0.7) -> DecisionService:
    return DecisionService(
        provider,
        model=MODEL,
        thresholds=DecisionThresholds(minimum_confidence=minimum),
        clock=Clock(),
        now=lambda: NOW,
    )


def decide(svc: DecisionService, **overrides: object) -> DecisionOutcome:
    kwargs: dict[str, object] = {"question": QUESTION, "options": OPTIONS, "subject": SUBJECT}
    kwargs.update(overrides)
    return svc.decide(**kwargs)  # type: ignore[arg-type]


@pytest.fixture
def telemetry_records() -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    root = logging.getLogger(ROOT_LOGGER_NAME)
    handler = Collect(level=logging.INFO)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield records
    finally:
        root.removeHandler(handler)


# --- decided -------------------------------------------------------------------------------------


def test_confident_valid_decision_is_decided() -> None:
    fake = FakeDecisionProvider("fake-decision", confidence=0.9)
    outcome = decide(service(fake), kind=DecisionKind.ROUTING)

    assert outcome.status is DecisionStatus.DECIDED
    assert not outcome.fallback_required
    assert outcome.fallback_reason is None
    assert outcome.choice == "bug"
    assert outcome.kind is DecisionKind.ROUTING
    (request,) = fake.requests
    assert request.model == "judge-v1"  # model id from models.yaml, never the alias
    assert request.subject == SUBJECT


@pytest.mark.parametrize("kind", list(DecisionKind))
def test_every_first_use_kind_is_supported(kind: DecisionKind) -> None:
    ordered = kind is DecisionKind.SEVERITY
    options = ("low", "medium", "high", "critical") if ordered else OPTIONS
    outcome = decide(
        service(FakeDecisionProvider("fake-decision", confidence=0.95)),
        kind=kind, options=options, ordered=ordered,
    )
    assert outcome.status is DecisionStatus.DECIDED
    assert outcome.result is not None and outcome.result.kind is kind
    assert (outcome.result.score is not None) is ordered


def test_confidence_equal_to_minimum_is_accepted() -> None:
    outcome = decide(service(FakeDecisionProvider("fake-decision", confidence=0.7), minimum=0.7))
    assert outcome.status is DecisionStatus.DECIDED


# --- fallback contract -------------------------------------------------------------------------


def test_low_confidence_requires_fallback_and_keeps_result_for_audit() -> None:
    outcome = decide(service(FakeDecisionProvider("fake-decision", confidence=0.4), minimum=0.7))

    assert outcome.status is DecisionStatus.FALLBACK_REQUIRED
    assert outcome.fallback_reason is FallbackReason.LOW_CONFIDENCE
    assert outcome.result is not None and outcome.result.choice == "bug"
    assert outcome.choice is None  # never accepted
    assert outcome.detail == "confidence 0.40 is below the minimum 0.70"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (DecisionUnavailableError, FallbackReason.UNAVAILABLE),
        (DecisionTimeoutError, FallbackReason.TIMEOUT),
        (DecisionInvalidResponseError, FallbackReason.INVALID_RESPONSE),
    ],
)
def test_provider_failures_require_fallback(
    error: type[ProviderCallError], reason: FallbackReason
) -> None:
    fake = FakeDecisionProvider("fake-decision", fail_with="boom", fail_as=error)
    outcome = decide(service(fake))

    assert outcome.status is DecisionStatus.FALLBACK_REQUIRED
    assert outcome.fallback_reason is reason
    assert outcome.result is None
    assert outcome.detail == "provider 'fake-decision' call failed: boom"


class _Fixed:
    """Adapter returning a fixed (possibly out-of-contract) result."""

    provider_id = "fake-decision"

    def __init__(self, **fields: object) -> None:
        self._fields = {"provider": "fake-decision", "model": "judge-v1", "choice": "bug",
                        "confidence": 1.0, **fields}

    def decide(self, request: object) -> DecisionResult:
        return DecisionResult.model_validate(self._fields)


@pytest.mark.parametrize(
    ("fields", "problem"),
    [
        ({"choice": "security"}, "choice is not one of"),
        ({"provider": "someone-else"}, "provider does not match"),
        ({"model": "other-model"}, "does not echo the requested model"),
        ({"kind": "routing"}, "does not echo the requested kind"),
        ({"score": 0.5}, "score reported for an unordered"),
        ({"probabilities": {"bug": 0.9, "feature": 0.1}}, "cover exactly the requested options"),
    ],
)
def test_contract_violations_are_rejected_at_the_harness_boundary(
    fields: dict[str, object], problem: str
) -> None:
    outcome = decide(service(_Fixed(**fields), minimum=0.0))

    assert outcome.fallback_reason is FallbackReason.INVALID_RESPONSE
    assert outcome.result is None and outcome.choice is None
    assert outcome.detail is not None and problem in outcome.detail


def test_rejected_credentials_are_raised_not_routed(
    telemetry_records: list[logging.LogRecord],
) -> None:
    fake = FakeDecisionProvider(fail_with="HTTP 401", fail_as=DecisionAuthenticationError)
    with pytest.raises(DecisionAuthenticationError):
        decide(service(fake))
    (record,) = telemetry_records
    event = json.loads(record.getMessage().removeprefix("decision "))
    assert event["status"] == "error"
    assert event["fallback_required"] is False
    assert event["error_category"] == "DecisionAuthenticationError"


def test_generic_provider_error_is_raised() -> None:
    with pytest.raises(ProviderCallError):
        decide(service(FakeDecisionProvider(fail_with="HTTP 422")))


def test_fallback_never_calls_an_llm() -> None:
    """V0.4 only signals fallbacks: nothing else is called, whatever the reason."""
    llm = FakeLLMProvider("openai")
    for fake in (
        FakeDecisionProvider("fake-decision", confidence=0.1),
        FakeDecisionProvider(fail_with="down", fail_as=DecisionUnavailableError),
        FakeDecisionProvider(fail_with="slow", fail_as=DecisionTimeoutError),
        FakeDecisionProvider(choice="nonsense"),
    ):
        outcome = decide(service(fake))
        assert outcome.fallback_required
        assert len(fake.requests) == 1  # no retry either
    assert llm.requests == []


def test_invalid_input_fails_before_any_provider_call() -> None:
    fake = FakeDecisionProvider()
    with pytest.raises(InvalidDecisionRequestError, match="options") as excinfo:
        decide(service(fake), options=("only-one",))
    with pytest.raises(InvalidDecisionRequestError, match="unknown options"):
        decide(service(fake), descriptions={"security": "not an option"})
    assert fake.requests == []
    assert SUBJECT not in str(excinfo.value)


def test_outcome_invariants() -> None:
    telemetry = decide(service(FakeDecisionProvider("fake-decision"))).telemetry
    with pytest.raises(ValidationError, match="needs a fallback reason"):
        DecisionOutcome(status=DecisionStatus.FALLBACK_REQUIRED, kind=DecisionKind.ROUTING,
                        telemetry=telemetry)
    with pytest.raises(ValidationError, match="has a result"):
        DecisionOutcome(status=DecisionStatus.DECIDED, kind=DecisionKind.ROUTING,
                        telemetry=telemetry)
    with pytest.raises(ValidationError, match="telemetry status"):
        DecisionOutcome(status=DecisionStatus.ERROR, kind=DecisionKind.ROUTING,
                        fallback_reason=FallbackReason.TIMEOUT, telemetry=telemetry)


# --- telemetry -----------------------------------------------------------------------------------


def test_telemetry_records_identity_metrics_and_timing(
    telemetry_records: list[logging.LogRecord],
) -> None:
    provider = JevDecisionProvider(api_key="test-key-not-a-secret", provider_id="fake-decision",
                                   transport=JevEmulator(pick="bug", peak=0.9))
    outcome = decide(service(provider))
    telemetry = outcome.telemetry

    assert telemetry.timestamp == NOW
    assert (telemetry.provider, telemetry.model_alias, telemetry.model) == (
        "fake-decision", "decision", "judge-v1",
    )
    assert telemetry.resolved_model == "jev-1.13.0"
    assert telemetry.kind is DecisionKind.CLASSIFICATION
    assert telemetry.option_count == 3
    assert telemetry.choice == "bug"
    assert telemetry.confidence == pytest.approx(0.85)
    assert telemetry.probability == pytest.approx(0.9)
    assert telemetry.duration_ms == pytest.approx(25.0)
    assert telemetry.minimum_confidence == 0.7
    assert telemetry.fallback_required is False
    assert telemetry.input_tokens == 296

    (record,) = telemetry_records
    assert record.name == TELEMETRY_LOGGER
    assert record.levelno == logging.INFO
    assert json.loads(record.getMessage().removeprefix("decision "))["choice"] == "bug"


def test_telemetry_of_a_fallback_has_reason_and_category(
    telemetry_records: list[logging.LogRecord],
) -> None:
    fake = FakeDecisionProvider(fail_with="slow", fail_as=DecisionTimeoutError)
    telemetry = decide(service(fake)).telemetry
    assert telemetry.fallback_required is True
    assert telemetry.fallback_reason is FallbackReason.TIMEOUT
    assert telemetry.error_category == "DecisionTimeoutError"
    assert telemetry.choice is None and telemetry.confidence is None


def test_telemetry_never_contains_question_subject_or_secrets(
    telemetry_records: list[logging.LogRecord],
) -> None:
    key = "sk-live-should-never-appear"
    provider = JevDecisionProvider(api_key=key, provider_id="fake-decision",
                                   transport=JevEmulator())
    outcome = decide(service(provider), descriptions={"bug": "Broken behaviour"})
    serialized = outcome.telemetry.model_dump_json() + "".join(
        r.getMessage() for r in telemetry_records
    )
    for sensitive in (QUESTION, SUBJECT, "alice", "Broken behaviour", key, "Bearer"):
        assert sensitive not in serialized


# --- health --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, HealthStatus.HEALTHY),
        ((401, {}), HealthStatus.MISCONFIGURED),
        ((529, {}), HealthStatus.UNAVAILABLE),
    ],
)
def test_health_maps_connectivity(
    status: tuple[int, dict[str, object]] | None, expected: HealthStatus
) -> None:
    emulator = JevEmulator()
    emulator.fail_status = status
    provider = JevDecisionProvider(api_key="k", provider_id="fake-decision", transport=emulator)
    health = service(provider).health()
    assert health.status is expected
    assert health.ok is (expected is HealthStatus.HEALTHY)
    assert all(path == "/v1/models" for _, path, _ in emulator.calls)


def test_health_of_an_offline_adapter() -> None:
    health = service(FakeDecisionProvider("fake-decision")).health()
    assert health.status is HealthStatus.HEALTHY
    assert "no connectivity check" in health.detail

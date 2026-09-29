"""Normalization: raw input from any origin -> EngineeringRequest."""

from __future__ import annotations

import pytest

from orchestrator.core.exceptions import InvalidRequestError, RequestError
from orchestrator.core.request import (
    EngineeringRequest,
    ExecutionMode,
    Intent,
    RequestSource,
)
from orchestrator.intake import normalize_request


def test_cli_input_becomes_interactive_request() -> None:
    request = normalize_request(source="cli", instruction="  add a health endpoint \n")

    assert isinstance(request, EngineeringRequest)
    assert request.mode is ExecutionMode.INTERACTIVE
    assert request.source is RequestSource.CLI
    assert request.intent is Intent.UNCLASSIFIED  # not guessed
    assert request.instruction == "add a health endpoint"
    assert request.origin_ref is None


def test_task_input_becomes_autonomous_request() -> None:
    request = normalize_request(
        source="task", instruction="implement T-3", intent="implement", origin_ref=" T-3 "
    )

    assert request.mode is ExecutionMode.AUTONOMOUS
    assert request.source is RequestSource.TASK
    assert request.intent is Intent.IMPLEMENT
    assert request.origin_ref == "T-3"


@pytest.mark.parametrize(
    ("source", "mode"),
    [
        ("cli", ExecutionMode.INTERACTIVE),
        ("mcp", ExecutionMode.INTERACTIVE),
        ("claude_code", ExecutionMode.INTERACTIVE),
        ("codex", ExecutionMode.INTERACTIVE),
        ("http_api", ExecutionMode.INTERACTIVE),
        ("roadmap", ExecutionMode.AUTONOMOUS),
        ("sprint", ExecutionMode.AUTONOMOUS),
        ("task", ExecutionMode.AUTONOMOUS),
        ("previous_run", ExecutionMode.AUTONOMOUS),
        ("persisted_state", ExecutionMode.AUTONOMOUS),
    ],
)
def test_mode_is_derived_from_source(source: str, mode: ExecutionMode) -> None:
    request = normalize_request(source=source, instruction="x", intent="plan", origin_ref="R-1")
    assert request.source == source
    assert request.mode is mode


def test_interactive_and_autonomous_share_the_same_contract() -> None:
    interactive = normalize_request(source="mcp", instruction="x")
    autonomous = normalize_request(source="sprint", instruction="x", intent="plan",
                                   origin_ref="sprint-v0.1")
    assert type(interactive) is type(autonomous) is EngineeringRequest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Claude-Code", RequestSource.CLAUDE_CODE),
        ("HTTP API", RequestSource.HTTP_API),
        ("  CLI ", RequestSource.CLI),
        ("previous-run", RequestSource.PREVIOUS_RUN),
    ],
)
def test_source_spelling_is_normalized(raw: str, expected: RequestSource) -> None:
    request = normalize_request(source=raw, instruction="x", intent="review", origin_ref="R-1")
    assert request.source is expected


def test_intent_spelling_is_normalized() -> None:
    assert normalize_request(source="cli", instruction="x", intent=" PLAN ").intent is Intent.PLAN


def test_explicit_matching_mode_is_accepted() -> None:
    request = normalize_request(source="cli", instruction="x", mode="Interactive")
    assert request.mode is ExecutionMode.INTERACTIVE


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"source": "slack"}, "source: unknown value 'slack'"),
        ({"source": ""}, "source: unknown value ''"),
        ({"intent": "deploy"}, "intent: unknown value 'deploy'"),
        ({"mode": "semi"}, "mode: unknown value 'semi'"),
        ({"instruction": "   "}, "instruction:"),
        ({"mode": "autonomous"}, "source 'cli' is not valid for mode 'autonomous'"),
        ({"source": "task", "intent": "implement"}, "require origin_ref"),
        ({"source": "task", "intent": "implement", "origin_ref": "  "}, "require origin_ref"),
        ({"source": "task", "origin_ref": "T-1"}, "require a classified intent"),
    ],
)
def test_invalid_input_raises_invalid_request_error(
    kwargs: dict[str, str], expected: str
) -> None:
    raw = {"source": "cli", "instruction": "x"} | kwargs
    with pytest.raises(InvalidRequestError, match=expected):
        normalize_request(**raw)


def test_invalid_request_error_is_a_request_error() -> None:
    assert issubclass(InvalidRequestError, RequestError)


def test_error_message_lists_allowed_values() -> None:
    with pytest.raises(InvalidRequestError, match="allowed: plan, implement, review, unclassified"):
        normalize_request(source="cli", instruction="x", intent="guess")

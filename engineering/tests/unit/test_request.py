"""Contract tests for the V0.1 domain: modes, sources, intents, EngineeringRequest."""

from __future__ import annotations

import itertools
import json
import uuid
from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.core.request import (
    REQUEST_SCHEMA_VERSION,
    SOURCES_BY_MODE,
    EngineeringRequest,
    ExecutionMode,
    Intent,
    RequestSource,
    WorkflowState,
    mode_for_source,
)

INTERACTIVE_SOURCES = sorted(SOURCES_BY_MODE[ExecutionMode.INTERACTIVE])
AUTONOMOUS_SOURCES = sorted(SOURCES_BY_MODE[ExecutionMode.AUTONOMOUS])


def _interactive(**overrides: Any) -> EngineeringRequest:
    fields: dict[str, Any] = {
        "mode": ExecutionMode.INTERACTIVE,
        "source": RequestSource.CLI,
        "instruction": "add a health endpoint",
    }
    return EngineeringRequest(**(fields | overrides))


def _autonomous(**overrides: Any) -> EngineeringRequest:
    fields: dict[str, Any] = {
        "mode": ExecutionMode.AUTONOMOUS,
        "source": RequestSource.TASK,
        "intent": Intent.IMPLEMENT,
        "instruction": "implement task T-1",
        "origin_ref": "T-1",
    }
    return EngineeringRequest(**(fields | overrides))


# --- enums: stable serialized values ---------------------------------------------


def test_execution_modes_are_exactly_interactive_and_autonomous() -> None:
    assert [m.value for m in ExecutionMode] == ["interactive", "autonomous"]


def test_request_sources_are_the_documented_origins() -> None:
    assert {s.value for s in RequestSource} == {
        "cli", "mcp", "claude_code", "codex", "http_api",
        "roadmap", "sprint", "task", "previous_run", "persisted_state",
    }


def test_intents_are_minimal() -> None:
    assert [i.value for i in Intent] == ["plan", "implement", "review", "unclassified"]


def test_only_initial_workflow_state_exists() -> None:
    assert list(WorkflowState) == [WorkflowState.PLANNED]


@pytest.mark.parametrize(
    ("enum", "value"),
    [(ExecutionMode, "semi"), (RequestSource, "slack"), (Intent, "deploy"), (ExecutionMode, "")],
)
def test_unknown_enum_values_are_rejected(enum: type[Any], value: str) -> None:
    with pytest.raises(ValueError, match="is not a valid"):
        enum(value)


# --- mode/source partition ---------------------------------------------------------


def test_every_source_belongs_to_exactly_one_mode() -> None:
    interactive, autonomous = SOURCES_BY_MODE.values()
    assert interactive.isdisjoint(autonomous)
    assert interactive | autonomous == set(RequestSource)
    for source in RequestSource:
        assert source in SOURCES_BY_MODE[mode_for_source(source)]


def test_sources_by_mode_is_read_only() -> None:
    with pytest.raises(TypeError):
        SOURCES_BY_MODE[ExecutionMode.INTERACTIVE] = frozenset()  # type: ignore[index]


@pytest.mark.parametrize("source", INTERACTIVE_SOURCES)
def test_interactive_accepts_interactive_sources(source: RequestSource) -> None:
    assert _interactive(source=source).source is source


@pytest.mark.parametrize("source", AUTONOMOUS_SOURCES)
def test_autonomous_accepts_autonomous_sources(source: RequestSource) -> None:
    assert _autonomous(source=source).source is source


@pytest.mark.parametrize(
    ("mode", "source"),
    [
        *itertools.product([ExecutionMode.INTERACTIVE], AUTONOMOUS_SOURCES),
        *itertools.product([ExecutionMode.AUTONOMOUS], INTERACTIVE_SOURCES),
    ],
)
def test_mode_source_mismatch_is_rejected(mode: ExecutionMode, source: RequestSource) -> None:
    factory = _interactive if mode is ExecutionMode.INTERACTIVE else _autonomous
    with pytest.raises(ValidationError, match=f"source '{source}' is not valid for mode '{mode}'"):
        factory(source=source)


# --- creation, defaults, required fields ----------------------------------------------


def test_valid_interactive_request_defaults() -> None:
    request = _interactive()
    assert request.schema_version == REQUEST_SCHEMA_VERSION == 1
    assert request.mode is ExecutionMode.INTERACTIVE
    assert request.intent is Intent.UNCLASSIFIED
    assert request.origin_ref is None
    assert request.request_id.version == 4
    assert request.created_at.utcoffset() is not None


def test_request_ids_are_unique() -> None:
    assert len({_interactive().request_id for _ in range(100)}) == 100


@pytest.mark.parametrize("field", ["mode", "source", "instruction"])
def test_required_fields(field: str) -> None:
    fields = {"mode": "interactive", "source": "cli", "instruction": "x"}
    del fields[field]
    with pytest.raises(ValidationError, match=f"{field}\n  Field required"):
        EngineeringRequest.model_validate(fields)


@pytest.mark.parametrize("instruction", ["", "   ", "\n\t "])
def test_blank_instruction_is_rejected(instruction: str) -> None:
    with pytest.raises(ValidationError, match="instruction"):
        _interactive(instruction=instruction)


def test_instruction_is_stripped_but_inner_text_preserved() -> None:
    assert _interactive(instruction="  line 1\n\nline 2  ").instruction == "line 1\n\nline 2"


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="provider"):
        _interactive(provider="openai")


def test_naive_created_at_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _interactive(created_at=datetime(2026, 1, 1))  # naive on purpose


def test_origin_ref_length_is_bounded() -> None:
    with pytest.raises(ValidationError, match="origin_ref"):
        _interactive(origin_ref="x" * 201)


def test_request_is_immutable() -> None:
    request = _interactive()
    with pytest.raises(ValidationError, match="frozen"):
        request.mode = ExecutionMode.AUTONOMOUS  # type: ignore[misc]


# --- mode-specific invariants -----------------------------------------------------------


def test_interactive_may_reference_an_artifact() -> None:
    assert _interactive(origin_ref="T-7").origin_ref == "T-7"


def test_autonomous_requires_origin_ref() -> None:
    with pytest.raises(ValidationError, match="autonomous requests require origin_ref"):
        _autonomous(origin_ref=None)


def test_blank_origin_ref_is_rejected() -> None:
    with pytest.raises(ValidationError, match="origin_ref"):
        _autonomous(origin_ref="   ")


def test_autonomous_requires_classified_intent() -> None:
    with pytest.raises(ValidationError, match="require a classified intent"):
        _autonomous(intent=Intent.UNCLASSIFIED)


# --- serialization --------------------------------------------------------------------


def test_json_round_trip_preserves_request() -> None:
    request = _autonomous()
    assert EngineeringRequest.model_validate_json(request.model_dump_json()) == request


def test_serialized_form_uses_stable_names_and_values() -> None:
    data = json.loads(_autonomous(source=RequestSource.PREVIOUS_RUN).model_dump_json())
    assert set(data) == {
        "schema_version", "request_id", "created_at", "mode", "source", "intent",
        "instruction", "origin_ref",
    }
    assert data["mode"] == "autonomous"
    assert data["source"] == "previous_run"
    assert data["intent"] == "implement"
    assert uuid.UUID(data["request_id"])


def test_rehydration_keeps_existing_id() -> None:
    request_id = uuid.uuid4()
    assert _interactive(request_id=request_id).request_id == request_id


def test_unknown_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        _interactive(schema_version=2)

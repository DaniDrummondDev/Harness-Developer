"""Core admission: the initial transition rule, identical for both modes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from orchestrator.config import load_config
from orchestrator.core.admission import INITIAL_STATE, admit
from orchestrator.core.exceptions import ModeNotEnabledError, RequestError
from orchestrator.core.request import (
    AdmittedRequest,
    EngineeringRequest,
    ExecutionMode,
    WorkflowState,
)
from orchestrator.intake import normalize_request

ALL_MODES = frozenset(ExecutionMode)


def _interactive() -> EngineeringRequest:
    return normalize_request(source="cli", instruction="x")


def _autonomous() -> EngineeringRequest:
    return normalize_request(source="task", instruction="x", intent="implement", origin_ref="T-1")


def test_initial_state_is_planned() -> None:
    assert INITIAL_STATE is WorkflowState.PLANNED


@pytest.mark.parametrize("make", [_interactive, _autonomous], ids=["interactive", "autonomous"])
def test_both_modes_enter_the_same_initial_state(make: Callable[[], EngineeringRequest]) -> None:
    request = make()
    admitted = admit(request, ALL_MODES)

    assert isinstance(admitted, AdmittedRequest)
    assert admitted.request is request  # the core keeps the normalized request untouched
    assert admitted.state is WorkflowState.PLANNED


@pytest.mark.parametrize(
    ("make", "enabled"),
    [
        (_autonomous, {ExecutionMode.INTERACTIVE}),
        (_interactive, {ExecutionMode.AUTONOMOUS}),
        (_interactive, set()),
    ],
)
def test_disabled_mode_is_refused(
    make: Callable[[], EngineeringRequest], enabled: set[ExecutionMode]
) -> None:
    request = make()
    with pytest.raises(ModeNotEnabledError, match=f"mode '{request.mode}' is not enabled"):
        admit(request, enabled)


def test_mode_not_enabled_is_a_request_error() -> None:
    assert issubclass(ModeNotEnabledError, RequestError)


def test_shipped_config_admits_interactive_and_refuses_autonomous(harness_root: Path) -> None:
    enabled = load_config(harness_root).enabled_modes

    assert admit(_interactive(), enabled).state is WorkflowState.PLANNED
    with pytest.raises(ModeNotEnabledError, match=r"enabled: interactive\)"):
        admit(_autonomous(), enabled)


def test_admitted_request_serializes_with_state() -> None:
    admitted = admit(_interactive(), ALL_MODES)
    restored = AdmittedRequest.model_validate_json(admitted.model_dump_json())
    assert restored == admitted
    assert admitted.model_dump(mode="json")["state"] == "planned"

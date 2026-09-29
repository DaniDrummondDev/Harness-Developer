"""Core entry point: admit a normalized request and assign its initial state.

This is the whole of the V0.1 "initial transition rule":

    EngineeringRequest --(mode enabled?)--> AdmittedRequest(state=PLANNED)
                       \\-(mode disabled)--> ModeNotEnabledError

The rule is identical for both modes: there is no per-mode branch, so
Interactive and Autonomous share the same core path. Which modes are enabled
is project configuration (`modes.yaml`); the caller passes it in, so the core
does not depend on YAML or on `orchestrator.config`.

Not here (later versions): transition graph, persistence, retries,
escalation, next-task selection (V6 / V13).
"""

from __future__ import annotations

from collections.abc import Set

from orchestrator.core.exceptions import ModeNotEnabledError
from orchestrator.core.request import (
    AdmittedRequest,
    EngineeringRequest,
    ExecutionMode,
    WorkflowState,
)

INITIAL_STATE = WorkflowState.PLANNED


def admit(request: EngineeringRequest, enabled_modes: Set[ExecutionMode]) -> AdmittedRequest:
    """Accept `request` into the workflow in `INITIAL_STATE`.

    Raises:
        ModeNotEnabledError: `request.mode` is not in `enabled_modes` (fail closed).
    """
    if request.mode not in enabled_modes:
        enabled = ", ".join(sorted(enabled_modes)) or "none"
        raise ModeNotEnabledError(
            f"mode '{request.mode}' is not enabled in modes.yaml (enabled: {enabled})"
        )
    return AdmittedRequest(request=request, state=INITIAL_STATE)

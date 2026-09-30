"""Planner output validation (V1.4): LLM text -> validated `ContextPlan`, or rejection.

The LLM output is never trusted. `LLMProvider` returns text only (no native
structured output in the contract), so the minimal vendor-neutral approach is:
the prompt demands one JSON object and this module enforces it strictly:

    1. parse    exactly one JSON object (a single surrounding ``` fence is
                tolerated, nothing else: no prose extraction, no repair)
    2. schema   `PlannerResponse`: exact keys (unexpected fields rejected, e.g. a
                "classification" the planner may not set), strict types, bounded sizes
    3. ids      every id was sent to the planner; no duplicates
    4. rules    every mandatory REQUIRED sent is selected (never re-added silently:
                an omission rejects the plan); nothing unavailable/excluded/unmeasured
    5. normalise  REQUIRED first (stable, keeps the planner's order inside each
                group), then REQUIRED withheld for safety appended by the Harness
    6. enforce  `plan_violations` replays the budget (fit, categories, max_*)

Any failure raises `InvalidPlanError` with every problem found; the planner turns
it into FAILED/invalid_output and the V1.3 result stands.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic import ValidationError as PydanticValidationError

from orchestrator.context.budget.models import BudgetedItem, ContextBudgetResult
from orchestrator.context.classification.models import ContextClass
from orchestrator.context.escalation.invariants import PlanningRole, plan_size, plan_violations
from orchestrator.context.escalation.models import (
    ConstraintKind,
    ContextPlan,
    UnresolvedConstraint,
)
from orchestrator.context.escalation.planning import ContextPlanningInput

MAX_RESPONSE_CHARACTERS = 200_000
_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class InvalidPlanError(ValueError):
    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


class PlannerResponse(BaseModel):
    """The exact JSON object the planner must return."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    selected_candidate_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=500)]
                                 ] = Field(max_length=2000)
    rationale: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                                max_length=4000)]
    unresolved_constraints: list[_Text] = Field(max_length=50)
    suggestions: list[_Text] = Field(max_length=20)


def parse_response(text: str) -> PlannerResponse:
    if len(text) > MAX_RESPONSE_CHARACTERS:
        raise InvalidPlanError([f"response longer than {MAX_RESPONSE_CHARACTERS} characters"])
    body = _unfence(text.strip())
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise InvalidPlanError([f"response is not a JSON object: {exc.msg} at {exc.pos}"]
                               ) from exc
    if not isinstance(data, dict):
        raise InvalidPlanError([f"response is a JSON {type(data).__name__}, not an object"])
    try:
        return PlannerResponse.model_validate(data)
    except PydanticValidationError as exc:
        raise InvalidPlanError([
            f"{'.'.join(str(p) for p in error['loc']) or '<root>'}: {error['msg']}"
            for error in exc.errors()
        ]) from exc


def validate_plan(response: PlannerResponse, budget: ContextBudgetResult,
                  planning_input: ContextPlanningInput, *,
                  constraints: Sequence[UnresolvedConstraint],
                  withheld_mandatory: Sequence[str] = ()) -> ContextPlan:
    items = {item.candidate.id: item for item in budget.items}
    sent = planning_input.candidate_ids()
    chosen = response.selected_candidate_ids
    problems = [f"'{cid}' is selected more than once"
                for cid in dict.fromkeys(c for c in chosen if chosen.count(c) > 1)]
    problems += [f"unknown candidate id '{cid}'" for cid in chosen if cid not in sent]
    problems += [f"REQUIRED '{c.id}' was omitted" for c in planning_input.candidates
                 if c.role is PlanningRole.MANDATORY and c.id not in chosen]
    if problems:
        raise InvalidPlanError(problems)

    required = [c for c in chosen if _required(items[c])]
    ordered = (*required, *withheld_mandatory, *(c for c in chosen if not _required(items[c])))
    problems = plan_violations(budget, ordered)
    if problems:
        raise InvalidPlanError(problems)

    deterministic = [i.candidate.id for i in budget.selected]
    return ContextPlan(
        selected_candidate_ids=ordered,
        rationale=response.rationale,
        added=tuple(c for c in ordered if c not in deterministic),
        dropped=tuple(c for c in deterministic if c not in ordered),
        used=plan_size(budget, ordered),
        usable=budget.limits.usable,
        unresolved_constraints=(
            *constraints,
            *(UnresolvedConstraint(kind=ConstraintKind.PLANNER_REPORTED, detail=text)
              for text in response.unresolved_constraints),
        ),
        suggestions=tuple(response.suggestions),
    )


def _required(item: BudgetedItem) -> bool:
    return item.classified.classification.classification is ContextClass.REQUIRED


def _unfence(text: str) -> str:
    if text.startswith("```") and text.endswith("```") and text.count("```") == 2:
        first_newline = text.find("\n")
        if first_newline != -1:
            return text[first_newline + 1:-3].strip()
    return text

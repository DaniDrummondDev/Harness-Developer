"""LLM Context Escalation contracts (V1.4).

Escalation answers two questions, in this order and by different means:

    1. "does this request need extra reasoning to plan its context?"
       -> `ContextEscalationDecision`, computed DETERMINISTICALLY from the V1.3
          budget result (never by asking an LLM whether to call an LLM)
    2. only when (1) is yes: "which context should be prioritised or reorganised
       within the existing constraints?"
       -> `ContextPlan`, proposed by the planner model (LLMProvider) and then
          validated deterministically (validation.py) before it exists

Triggers (`EscalationReason`) exist only where real data supports them; high
risk has no source yet (risk engine: V9) and is deliberately absent.

The plan never changes earlier decisions: it carries no classification, it
cannot drop REQUIRED, select EXCLUDED, invent ids, select an unavailable or
unmeasured item, or exceed the budget without it being reported. Its
`unresolved_constraints` always start with the Harness's own (deterministic)
constraints, so an overflow can never be hidden by the planner.

`ContextEscalationResult` always keeps the V1.3 `ContextBudgetResult` untouched:
on NOT_REQUIRED or FAILED it is the result to use (fallback = deterministic).

    status        when                                           plan   llm_calls
    NOT_REQUIRED  no trigger fired (or escalation disabled)      None   0
    PLANNED       the planner answered and the plan validated    set    1
    FAILED        escalation required but no valid plan:         None   0 or 1
                  planner unavailable / unsafe input (0 calls),
                  provider error / invalid output (1 call)
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestrator.context.budget.models import ContextBudgetResult
from orchestrator.context.escalation.invariants import plan_violations


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EscalationReason(StrEnum):
    """A deterministic trigger. Declaration order = evaluation and output order."""

    ARCHITECTURAL_TASK = "architectural_task"  # declared intent (context.yaml list)
    MULTIPLE_DOMAINS = "multiple_domains"  # >= N REQUIRED/HIGH_VALUE specialties
    LOW_CONFIDENCE = "low_confidence"  # >= N decisions below the decision threshold
    TOO_MANY_RELEVANT_CANDIDATES = "too_many_relevant_candidates"  # > N HIGH_VALUE
    SOURCE_CONFLICT = "source_conflict"  # metadata conflict recorded by discovery merge
    REQUIRED_OVERFLOW = "required_overflow"  # REQUIRED alone exceeds `usable`
    REQUIRED_UNAVAILABLE = "required_unavailable"  # a REQUIRED item has no content


class EscalationEvidence(_Model):
    """Why one trigger fired: what was observed against which configured threshold,
    and which candidates are involved (audit trail)."""

    reason: EscalationReason
    detail: str = Field(min_length=1)
    observed: int | None = Field(default=None, ge=0)
    threshold: int | None = Field(default=None, ge=0)
    candidate_ids: tuple[str, ...] = ()


class ContextEscalationDecision(_Model):
    required: bool
    reasons: tuple[EscalationReason, ...] = ()
    evidence: tuple[EscalationEvidence, ...] = ()
    evaluated: bool = Field(default=True, description="False when escalation is disabled.")

    @classmethod
    def of(cls, evidence: tuple[EscalationEvidence, ...]) -> ContextEscalationDecision:
        return cls(required=bool(evidence), reasons=tuple(e.reason for e in evidence),
                   evidence=evidence)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.reasons != tuple(e.reason for e in self.evidence):
            raise ValueError("reasons must list the evidence reasons, in order")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("a reason is recorded once")
        if self.required != bool(self.reasons):
            raise ValueError("escalation is required exactly when a trigger fired")
        if not self.evaluated and self.required:
            raise ValueError("a disabled escalation cannot require planning")
        return self


class ConstraintKind(StrEnum):
    REQUIRED_OVERFLOW = "required_overflow"
    REQUIRED_UNAVAILABLE = "required_unavailable"
    SOURCE_CONFLICT = "source_conflict"
    LIMIT_CONFLICT = "limit_conflict"  # budget: REQUIRED exceeds a category/max_* limit
    WITHHELD = "withheld"  # not sent to the planner: failed the safety check
    PLANNER_REPORTED = "planner_reported"  # stated by the planner (not verified)


class UnresolvedConstraint(_Model):
    kind: ConstraintKind
    detail: str = Field(min_length=1)
    candidate_ids: tuple[str, ...] = ()

    @property
    def from_planner(self) -> bool:
        return self.kind is ConstraintKind.PLANNER_REPORTED


class ContextPlan(_Model):
    """A validated recommendation for organising the context. Not a prompt.

    - `selected_candidate_ids`: what the plan selects, in priority order
      (every available REQUIRED first, whole items only);
    - `added` / `dropped`: difference against the V1.3 selection (audit);
    - `used` / `usable`: characters of the plan's selection vs the budget;
    - `unresolved_constraints`: the Harness's constraints, then the planner's;
    - `suggestions`: planner proposals the Harness never executes (truncation,
      chunking, summarisation, asking a human...).
    """

    selected_candidate_ids: tuple[str, ...]
    rationale: str = Field(min_length=1)
    added: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    used: int = Field(ge=0)
    usable: int = Field(ge=1)
    unresolved_constraints: tuple[UnresolvedConstraint, ...] = ()
    suggestions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.selected_candidate_ids)) != len(self.selected_candidate_ids):
            raise ValueError("a candidate is selected at most once")
        if set(self.added) - set(self.selected_candidate_ids):
            raise ValueError("added ids must be selected")
        if set(self.dropped) & set(self.selected_candidate_ids):
            raise ValueError("dropped ids cannot be selected")
        return self


class PlanningFailure(StrEnum):
    PLANNER_UNAVAILABLE = "planner_unavailable"  # no model / provider disabled / no adapter
    UNSAFE_INPUT = "unsafe_input"  # the request text failed the safety check: nothing sent
    PROVIDER_ERROR = "provider_error"  # the LLMProvider raised (timeout, 5xx, auth...)
    INVALID_OUTPUT = "invalid_output"  # malformed JSON, schema or invariant violation


_CALLED = frozenset({PlanningFailure.PROVIDER_ERROR, PlanningFailure.INVALID_OUTPUT})


class PlannerCall(_Model):
    """Metadata of the one LLM call (no prompt, no output text: auditability
    without leaking the request)."""

    model_alias: str
    provider: str
    model_id: str
    duration_ms: int = Field(ge=0)
    prompt_characters: int = Field(ge=0)
    response_characters: int | None = Field(default=None, ge=0)  # None: no response


class PlanStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PLANNED = "PLANNED"
    FAILED = "FAILED"


class ContextEscalationResult(_Model):
    """V1.3 budget (always kept) + escalation decision + optional validated plan.

    `constraints`: the Harness's deterministic unresolved constraints (empty when
    no escalation was required). `failure` / `failure_kind`: why FAILED. `warnings`:
    the budget's, then `escalation:` ones."""

    budget: ContextBudgetResult
    escalation: ContextEscalationDecision
    status: PlanStatus
    constraints: tuple[UnresolvedConstraint, ...] = ()
    plan: ContextPlan | None = None
    failure_kind: PlanningFailure | None = None
    failure: str | None = None
    call: PlannerCall | None = None
    llm_calls: int = Field(default=0, ge=0, le=1)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.status is PlanStatus.NOT_REQUIRED) == self.escalation.required:
            raise ValueError("NOT_REQUIRED exactly when no escalation is required")
        if (self.plan is not None) != (self.status is PlanStatus.PLANNED):
            raise ValueError("a plan exists exactly when PLANNED")
        if (self.failure_kind is not None) != (self.status is PlanStatus.FAILED) or (
                (self.failure is not None) != (self.failure_kind is not None)):
            raise ValueError("a failure (kind and detail) exists exactly when FAILED")
        if (self.call is not None) != (self.llm_calls == 1):
            raise ValueError("call metadata exists exactly when the LLM was called")
        called = self.status is PlanStatus.PLANNED or self.failure_kind in _CALLED
        if called != (self.llm_calls == 1):
            raise ValueError("the LLM is called for PLANNED / provider_error / invalid_output only")
        if self.status is PlanStatus.NOT_REQUIRED and self.constraints:
            raise ValueError("constraints are computed only for an escalation")
        if self.plan is not None:
            harness = tuple(c for c in self.plan.unresolved_constraints if not c.from_planner)
            if harness != self.constraints:
                raise ValueError("the plan must report every Harness constraint, unchanged")
            problems = plan_violations(self.budget, self.plan.selected_candidate_ids)
            if problems:
                raise ValueError("invalid plan: " + "; ".join(problems))
        return self

    @property
    def unresolved_constraints(self) -> tuple[UnresolvedConstraint, ...]:
        return self.plan.unresolved_constraints if self.plan is not None else self.constraints

    def summary(self) -> dict[str, object]:
        """The short answer (CLI): escalated? why? who planned? what is left open?"""
        return {
            "escalation_required": self.escalation.required,
            "reasons": [str(r) for r in self.escalation.reasons],
            "plan_status": str(self.status),
            "llm_calls": self.llm_calls,
            "provider": self.call.provider if self.call else None,
            "model": self.call.model_alias if self.call else None,
            "budget_status": str(self.budget.status),
            "selected_count": len(self.plan.selected_candidate_ids) if self.plan
            else len(self.budget.selected),
            "selection_source": "plan" if self.plan else "deterministic_budget",
            "unresolved_constraints": [c.kind.value for c in self.unresolved_constraints],
            "failure": self.failure,
        }

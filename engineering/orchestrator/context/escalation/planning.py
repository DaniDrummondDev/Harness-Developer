"""Safe planner input (V1.4): ContextBudgetResult -> ContextPlanningInput -> prompt.

`ContextPlanningInput` is the ONLY thing serialised into the planner prompt. It
is an explicit allow-list of fields, never a dump of internal objects:

    sent                                         never sent
    request: intent, mode, source, instruction   request id, timestamps, origin_ref
    budget: status, limits, usage                candidate CONTENT (no text, no excerpt)
    per candidate: id, kind, title, class,       library descriptions, memory excerpts,
      selected_by, evidence, confidence, size,   provenance reasons, file paths beyond
      category, budget reason, role, conflicts   the candidate id
    escalation reasons, Harness constraints      withheld candidates (only their count)

Safety (reusing the memory safe-ingestion policy, `memory.safety.evaluate`, and
discovery's secret file-name rule, `context.files.is_secret_name`):

- a candidate whose id/title/path/conflicts look secret, or whose project path
  has a secret-looking name (`.env`, keys, credentials...), is WITHHELD: not
  sent, recorded as a `withheld` constraint (never silent). A withheld
  REQUIRED stays REQUIRED: the Harness adds it to the plan itself;
- a secret-looking request instruction blocks the whole call (UNSAFE_INPUT):
  the task cannot be planned without it and it cannot be sent;
- the final rendered prompt is checked once more before any call.

Findings name rules, never matched text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict

from orchestrator.context.budget.models import BudgetedItem, ContextBudgetResult
from orchestrator.context.classification.models import ContextClass
from orchestrator.context.escalation.invariants import PlanningRole, planning_role
from orchestrator.context.escalation.models import (
    ConstraintKind,
    ContextEscalationDecision,
    UnresolvedConstraint,
)
from orchestrator.context.files import is_secret_name
from orchestrator.context.models import MERGE_CONFLICTS_KEY, ReferenceStore
from orchestrator.memory import safety


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanningRequest(_Model):
    intent: str
    mode: str
    source: str
    instruction: str


class PlanningBudget(_Model):
    status: str
    unit: str
    truncation: str
    total: int
    reserve: int
    usable: int
    used: int
    remaining: int
    overflow: int
    category_limits: dict[str, int]
    max_files: int
    max_adrs: int
    max_memories: int


class PlanningCandidate(_Model):
    id: str
    kind: str
    title: str
    classification: str
    selected_by: str
    evidence: str
    confidence: float | None
    category: str
    size: int | None
    budget_reason: str
    selected_by_budget: bool
    role: PlanningRole
    conflicts: tuple[str, ...] = ()


class PlanningConstraint(_Model):
    kind: str
    detail: str
    candidate_ids: tuple[str, ...] = ()


class ContextPlanningInput(_Model):
    request: PlanningRequest
    budget: PlanningBudget
    escalation_reasons: tuple[str, ...]
    candidates: tuple[PlanningCandidate, ...]
    constraints: tuple[PlanningConstraint, ...]
    withheld_candidates: int = 0

    def candidate_ids(self) -> frozenset[str]:
        return frozenset(c.id for c in self.candidates)


@dataclass(frozen=True, slots=True)
class PreparedInput:
    """`input` is None when the request itself is unsafe (`blocked_rules` says why)."""

    input: ContextPlanningInput | None
    withheld: tuple[UnresolvedConstraint, ...]
    withheld_mandatory: tuple[str, ...]
    blocked_rules: tuple[str, ...] = ()


def harness_constraints(budget: ContextBudgetResult) -> tuple[UnresolvedConstraint, ...]:
    """What the deterministic stages could not resolve; every plan reports these."""
    found: list[UnresolvedConstraint] = []
    usage = budget.usage
    if usage.overflow:
        found.append(UnresolvedConstraint(
            kind=ConstraintKind.REQUIRED_OVERFLOW,
            detail=f"REQUIRED context ({usage.used} characters) exceeds the usable budget "
                   f"({usage.usable}) by {usage.overflow}; REQUIRED is never removed",
            candidate_ids=tuple(i.candidate.id for i in budget.selected if _required(i)),
        ))
    found.extend(
        UnresolvedConstraint(kind=ConstraintKind.REQUIRED_UNAVAILABLE,
                             detail=f"REQUIRED without loadable content: {i.detail}",
                             candidate_ids=(i.candidate.id,))
        for i in budget.not_selected if _required(i)
    )
    found.extend(
        UnresolvedConstraint(kind=ConstraintKind.SOURCE_CONFLICT,
                             detail="conflicting metadata from different sources: "
                                    + "; ".join(_conflicts(i)),
                             candidate_ids=(i.candidate.id,))
        for i in (*budget.selected, *budget.not_selected) if _conflicts(i)
    )
    found.extend(
        UnresolvedConstraint(
            kind=ConstraintKind.LIMIT_CONFLICT,
            detail=f"REQUIRED items exceed {c.limit}{f' {c.category}' if c.category else ''} "
                   f"({c.required} > {c.configured}); kept",
        )
        for c in budget.conflicts
    )
    return tuple(found)


def prepare_input(budget: ContextBudgetResult, decision: ContextEscalationDecision,
                  constraints: tuple[UnresolvedConstraint, ...]) -> PreparedInput:
    withheld: list[UnresolvedConstraint] = []
    withheld_mandatory: list[str] = []
    candidates: list[PlanningCandidate] = []
    for item in budget.items:
        rules = _unsafe(item)
        if rules:
            withheld.append(UnresolvedConstraint(
                kind=ConstraintKind.WITHHELD, candidate_ids=(item.candidate.id,),
                detail=f"not sent to the planner (safety rules: {', '.join(rules)}); "
                       "the planner cannot select it",
            ))
            if planning_role(item) is PlanningRole.MANDATORY:
                withheld_mandatory.append(item.candidate.id)
            continue
        candidates.append(_candidate(item))

    request = budget.request
    blocked = safety.evaluate(request.instruction).rules
    if blocked:
        return PreparedInput(None, tuple(withheld), tuple(withheld_mandatory), blocked)
    sent = frozenset(c.id for c in candidates)
    limits, usage = budget.limits, budget.usage
    return PreparedInput(
        ContextPlanningInput(
            request=PlanningRequest(intent=request.intent, mode=request.mode,
                                    source=request.source, instruction=request.instruction),
            budget=PlanningBudget(
                status=budget.status, unit=limits.unit, truncation=limits.truncation,
                total=limits.total, reserve=limits.reserve, usable=limits.usable,
                used=usage.used, remaining=usage.remaining, overflow=usage.overflow,
                category_limits={name: cap for name, cap in limits.categories.model_dump().items()
                                 if cap is not None},
                max_files=limits.max_files, max_adrs=limits.max_adrs,
                max_memories=limits.max_memories,
            ),
            escalation_reasons=tuple(str(r) for r in decision.reasons),
            candidates=tuple(candidates),
            constraints=tuple(_sendable(c, sent) for c in constraints),
            withheld_candidates=len(withheld),
        ),
        tuple(withheld), tuple(withheld_mandatory),
    )


_INSTRUCTIONS = """\
You are the context planner of an engineering harness.
You are planning context, not solving the task: do not write code, do not answer,
perform or advise on the task itself. Work only on selecting and ordering context.

Choose which candidates to select and their priority order, within these rules
(a plan that breaks any rule is rejected and discarded):
- REQUIRED candidates cannot be removed: select every candidate whose role is "mandatory".
- EXCLUDED candidates cannot be selected; neither can any candidate whose role is
  "unavailable" (REQUIRED without content: never pretend it exists) or "not_selectable".
- Do not invent candidate ids: use only ids listed in the input.
- Do not alter classifications: no candidate changes class.
- Respect budget constraints: whole items only; the selected sizes must fit budget.usable,
  budget.category_limits and max_files / max_adrs / max_memories. REQUIRED always counts first.
- No truncation, chunking or summarisation will be executed; put such ideas in "suggestions".
- Report unresolved conflicts explicitly in "unresolved_constraints"; never choose
  silently between conflicting sources.

Answer with exactly one JSON object and nothing else, with exactly these keys:
{"selected_candidate_ids": [string, ...], "rationale": string,
 "unresolved_constraints": [string, ...], "suggestions": [string, ...]}
"selected_candidate_ids" is the priority order, most important first.

Input (JSON):
"""


def render_prompt(planning_input: ContextPlanningInput) -> str:
    """Fixed instructions + the allow-listed input as canonical JSON (stable order)."""
    payload = json.dumps(planning_input.model_dump(mode="json"), ensure_ascii=False,
                         sort_keys=True, indent=1)
    return _INSTRUCTIONS + payload  # no trailing whitespace: LLMRequest strips it


def _required(item: BudgetedItem) -> bool:
    return item.classified.classification.classification is ContextClass.REQUIRED


def _conflicts(item: BudgetedItem) -> tuple[str, ...]:
    value = item.candidate.metadata.get(MERGE_CONFLICTS_KEY, ())
    return value if isinstance(value, tuple) else (str(value),)


def _unsafe(item: BudgetedItem) -> tuple[str, ...]:
    candidate = item.candidate
    rules: list[str] = []
    if candidate.reference.store is ReferenceStore.PROJECT and any(
            is_secret_name(part) for part in PurePosixPath(candidate.reference.path).parts):
        rules.append("secret_file_name")
    for text in (candidate.id, candidate.title, candidate.reference.path, *_conflicts(item)):
        rules.extend(safety.evaluate(text).rules)
    return tuple(dict.fromkeys(rules))


def _candidate(item: BudgetedItem) -> PlanningCandidate:
    decision = item.classified.classification
    return PlanningCandidate(
        id=item.candidate.id, kind=item.candidate.kind, title=item.candidate.title,
        classification=decision.classification, selected_by=decision.selected_by,
        evidence=decision.evidence, confidence=decision.confidence, category=item.category,
        size=item.size, budget_reason=item.reason,
        selected_by_budget=item.content is not None, role=planning_role(item),
        conflicts=_conflicts(item),
    )


def _sendable(constraint: UnresolvedConstraint, sent: frozenset[str]) -> PlanningConstraint:
    """Only ids the planner can see; a detail that fails the safety check is replaced."""
    detail = constraint.detail
    if safety.evaluate(detail).rules:
        detail = f"{constraint.kind} (detail withheld: failed the safety check)"
    return PlanningConstraint(kind=constraint.kind, detail=detail,
                              candidate_ids=tuple(c for c in constraint.candidate_ids if c in sent))

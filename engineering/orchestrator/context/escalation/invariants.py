"""Deterministic plan invariants (V1.4): what any ContextPlan must respect.

Used twice, on purpose: by the output validator (validation.py) to reject a
planner answer, and by `ContextEscalationResult` itself so no code path can
construct a result holding an invalid plan.

    role            candidate                                        in a plan
    mandatory       REQUIRED with loaded content (budget: required)  always
    selectable      HIGH_VALUE/OPTIONAL with a measured size         optional
    unavailable     REQUIRED without loadable content                never (cannot be
                                                                     selected as if it
                                                                     had content)
    not_selectable  EXCLUDED, or never measured by the budget        never
                    (required_overflow, max_*_reached, unavailable)

Fit is replayed with the V1.3 rules (whole items): every mandatory item first
(it may overflow: REQUIRED is never limited), then each selected item in plan
order must fit the remaining usable budget, its category remainder and the
max_files/max_adrs/max_memories counts. A plan can reorganise; it cannot buy
room the deterministic budget does not have.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from orchestrator.context.budget.models import (
    BudgetCategory,
    BudgetedItem,
    BudgetReason,
    ContextBudgetResult,
    is_file,
)
from orchestrator.context.classification.models import ContextClass
from orchestrator.context.models import CandidateKind


class PlanningRole(StrEnum):
    """What the planner may do with a candidate (computed by the Harness)."""

    MANDATORY = "mandatory"
    SELECTABLE = "selectable"
    UNAVAILABLE = "unavailable"
    NOT_SELECTABLE = "not_selectable"


def planning_role(item: BudgetedItem) -> PlanningRole:
    cls = item.classified.classification.classification
    if cls is ContextClass.REQUIRED:
        return (PlanningRole.MANDATORY if item.reason is BudgetReason.REQUIRED
                else PlanningRole.UNAVAILABLE)
    if (cls is ContextClass.EXCLUDED or item.size is None
            or item.reason is BudgetReason.CONTENT_UNAVAILABLE):
        return PlanningRole.NOT_SELECTABLE
    return PlanningRole.SELECTABLE


def plan_violations(budget: ContextBudgetResult, selected_ids: Sequence[str]) -> list[str]:
    """Every invariant the selection breaks (empty = valid). Order-sensitive:
    fit is checked in plan order after the mandatory items."""
    items = {item.candidate.id: item for item in budget.items}
    problems: list[str] = []
    seen: set[str] = set()
    for cid in selected_ids:
        if cid in seen:
            problems.append(f"'{cid}' is selected more than once")
        seen.add(cid)
        item = items.get(cid)
        if item is None:
            problems.append(f"unknown candidate id '{cid}'")
            continue
        role = planning_role(item)
        if role is PlanningRole.UNAVAILABLE:
            problems.append(f"REQUIRED '{cid}' has no loadable content and cannot be selected")
        elif role is PlanningRole.NOT_SELECTABLE:
            cls = item.classified.classification.classification
            why = "EXCLUDED" if cls is ContextClass.EXCLUDED else f"not measured ({item.reason})"
            problems.append(f"'{cid}' is not selectable: {why}")
    mandatory = [i for i in budget.items if planning_role(i) is PlanningRole.MANDATORY]
    problems.extend(f"REQUIRED '{i.candidate.id}' is missing from the plan"
                    for i in mandatory if i.candidate.id not in seen)
    if problems:
        return problems
    return _fit_problems(budget, mandatory,
                         [items[c] for c in selected_ids
                          if planning_role(items[c]) is PlanningRole.SELECTABLE])


def plan_size(budget: ContextBudgetResult, selected_ids: Sequence[str]) -> int:
    sizes = {item.candidate.id: item.size or 0 for item in budget.items}
    return sum(sizes[cid] for cid in selected_ids)


def _fit_problems(budget: ContextBudgetResult, mandatory: Sequence[BudgetedItem],
                  chosen: Sequence[BudgetedItem]) -> list[str]:
    limits = budget.limits
    used = sum(i.size or 0 for i in mandatory)
    by_category = dict.fromkeys(BudgetCategory, 0)
    counts = {"files": 0, "adrs": 0, "memories": 0}
    for item in mandatory:
        _count(item, by_category, counts)
    problems: list[str] = []
    for item in chosen:
        size = item.size or 0
        cid = item.candidate.id
        cap = getattr(limits.categories, item.category.value)
        kind = item.candidate.kind
        if kind is CandidateKind.MEMORY and counts["memories"] >= limits.max_memories:
            problems.append(f"'{cid}' exceeds max_memories ({limits.max_memories})")
        elif kind is CandidateKind.ADR and counts["adrs"] >= limits.max_adrs:
            problems.append(f"'{cid}' exceeds max_adrs ({limits.max_adrs})")
        elif is_file(item.candidate) and counts["files"] >= limits.max_files:
            problems.append(f"'{cid}' exceeds max_files ({limits.max_files})")
        elif used + size > limits.usable:
            problems.append(f"'{cid}' ({size} characters) does not fit the usable budget "
                            f"({limits.usable - used} of {limits.usable} left)")
        elif cap is not None and by_category[item.category] + size > cap:
            problems.append(f"'{cid}' ({size} characters) exceeds the {item.category} limit "
                            f"({cap})")
        else:
            used += size
            _count(item, by_category, counts)
    return problems


def _count(item: BudgetedItem, by_category: dict[BudgetCategory, int],
           counts: dict[str, int]) -> None:
    by_category[item.category] += item.size or 0
    counts["files"] += is_file(item.candidate)
    counts["adrs"] += item.candidate.kind is CandidateKind.ADR
    counts["memories"] += item.candidate.kind is CandidateKind.MEMORY

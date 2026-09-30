"""Context Budget contracts (V1.3).

The budget answers "given the classified candidates, which ones fit and which
stay out?". It never reclassifies: the class (V1.2) is its input and its
authority. Each classified candidate gets exactly one budget decision, a layer
separate from — and never overwriting — the classification's own reason:

    list          reason (BudgetReason)          when
    selected      required                       class REQUIRED (always, content loaded)
                  within_budget                  HIGH_VALUE/OPTIONAL fitting every limit
    not_selected  content_unavailable            content could not be loaded safely
                                                 (a REQUIRED here -> REQUIRED_UNAVAILABLE)
                  required_overflow              not considered: REQUIRED exceeds `usable`
                  max_files_reached / max_adrs_reached / max_memories_reached
                  item_too_large                 larger than `usable` or its category limit
                  total_budget_exhausted         does not fit the remaining usable budget
                  category_budget_exhausted      does not fit its category's remainder
    excluded      excluded_by_classification     class EXCLUDED: never loaded, never selected

Status (worst first): REQUIRED_UNAVAILABLE (a REQUIRED item has no loadable
content) > REQUIRED_OVERFLOW (the REQUIRED set alone exceeds `usable`) > SUCCESS.
Neither failure removes a REQUIRED item: the selection is reported as is and
the caller must escalate (V1.4 / human), never send it silently.

Sizes are characters (`len` of the loaded text: Unicode code points). Items are
whole (`truncation: whole_item`): `included_size` is `size` when selected, 0
otherwise. Invariants below are validated, so an impossible result (a REQUIRED
dropped for budget, an EXCLUDED selected, usage not matching the items) cannot
be constructed.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestrator.config import BudgetSection
from orchestrator.context.classification.models import ClassifiedContextCandidate, ContextClass
from orchestrator.context.models import CandidateKind, ContextCandidate, ReferenceStore
from orchestrator.core.request import EngineeringRequest


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BudgetCategory(StrEnum):
    """One per real source family (field names of config `CategoryLimits`)."""

    LIBRARY = "library"
    INSTRUCTIONS = "instructions"
    ADRS = "adrs"
    DOCUMENTATION = "documentation"
    SOURCE_CODE = "source_code"
    MEMORY = "memory"


CATEGORY_BY_KIND: dict[CandidateKind, BudgetCategory] = {
    CandidateKind.POLICY: BudgetCategory.LIBRARY,
    CandidateKind.GUIDELINE: BudgetCategory.LIBRARY,
    CandidateKind.RULE: BudgetCategory.LIBRARY,
    CandidateKind.SKILL: BudgetCategory.LIBRARY,
    CandidateKind.SPECIALTY: BudgetCategory.LIBRARY,
    CandidateKind.PROJECT_INSTRUCTIONS: BudgetCategory.INSTRUCTIONS,
    CandidateKind.ADR: BudgetCategory.ADRS,
    CandidateKind.DOCUMENTATION: BudgetCategory.DOCUMENTATION,
    CandidateKind.SOURCE_CODE: BudgetCategory.SOURCE_CODE,
    CandidateKind.MEMORY: BudgetCategory.MEMORY,
}


def is_file(candidate: ContextCandidate) -> bool:
    """Counts toward `max_files`: a project file (library artifacts do not)."""
    return candidate.reference.store is ReferenceStore.PROJECT


class BudgetStatus(StrEnum):
    SUCCESS = "SUCCESS"
    REQUIRED_OVERFLOW = "REQUIRED_OVERFLOW"
    REQUIRED_UNAVAILABLE = "REQUIRED_UNAVAILABLE"


class BudgetReason(StrEnum):
    REQUIRED = "required"
    WITHIN_BUDGET = "within_budget"
    EXCLUDED_BY_CLASSIFICATION = "excluded_by_classification"
    CONTENT_UNAVAILABLE = "content_unavailable"
    REQUIRED_OVERFLOW = "required_overflow"
    MAX_FILES_REACHED = "max_files_reached"
    MAX_ADRS_REACHED = "max_adrs_reached"
    MAX_MEMORIES_REACHED = "max_memories_reached"
    ITEM_TOO_LARGE = "item_too_large"
    TOTAL_BUDGET_EXHAUSTED = "total_budget_exhausted"
    CATEGORY_BUDGET_EXHAUSTED = "category_budget_exhausted"


SELECTED_REASONS = frozenset({BudgetReason.REQUIRED, BudgetReason.WITHIN_BUDGET})
EXCLUDED_REASONS = frozenset({BudgetReason.EXCLUDED_BY_CLASSIFICATION})
NOT_SELECTED_REASONS = frozenset(BudgetReason) - SELECTED_REASONS - EXCLUDED_REASONS


class BudgetedItem(_Model):
    """One classified candidate (untouched, composition) and its budget decision.

    `size`: characters of the loaded content; None when it was never loaded
    (excluded, not considered, count limit reached, content unavailable).
    `content`: the loaded text of a selected item only. `detail`: human words
    for `content_unavailable` (why it could not be loaded)."""

    classified: ClassifiedContextCandidate
    category: BudgetCategory
    reason: BudgetReason
    size: int | None = Field(default=None, ge=0)
    included_size: int = Field(default=0, ge=0)
    detail: str | None = None
    content: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        cls = self.classified.classification.classification
        if self.category is not CATEGORY_BY_KIND[self.classified.candidate.kind]:
            raise ValueError("category does not match the candidate kind")
        if (self.reason is BudgetReason.REQUIRED) != (
            cls is ContextClass.REQUIRED and self.reason in SELECTED_REASONS
        ):
            raise ValueError("a REQUIRED candidate is selected as 'required' and only it")
        if cls is ContextClass.REQUIRED and self.reason not in (
            BudgetReason.REQUIRED, BudgetReason.CONTENT_UNAVAILABLE
        ):
            raise ValueError("a REQUIRED candidate is never left out for budget reasons")
        if (cls is ContextClass.EXCLUDED) != (self.reason in EXCLUDED_REASONS):
            raise ValueError("EXCLUDED candidates, and only they, are excluded_by_classification")
        if self.reason in SELECTED_REASONS:
            if self.size is None or self.content is None or len(self.content) != self.size:
                raise ValueError("a selected item carries its content and exact size")
            if self.included_size != self.size:
                raise ValueError("whole-item selection: included_size == size")
        elif self.content is not None or self.included_size:
            raise ValueError("an item that is not selected carries no content")
        if (self.detail is not None) != (self.reason is BudgetReason.CONTENT_UNAVAILABLE):
            raise ValueError("detail explains content_unavailable, and only it")
        return self

    @property
    def candidate(self) -> ContextCandidate:
        return self.classified.candidate


class LimitKind(StrEnum):
    CATEGORY = "category"
    MAX_FILES = "max_files"
    MAX_ADRS = "max_adrs"
    MAX_MEMORIES = "max_memories"


class LimitConflict(_Model):
    """A configured limit that the REQUIRED items alone exceed. REQUIRED wins
    (classification safety > budget convenience); the conflict is recorded."""

    limit: LimitKind
    category: BudgetCategory | None = None
    configured: int = Field(ge=0)
    required: int = Field(ge=0, description="What the REQUIRED items use of this limit.")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.category is not None) != (self.limit is LimitKind.CATEGORY):
            raise ValueError("a category conflict names its category, and only it")
        if self.required <= self.configured:
            raise ValueError("a conflict means REQUIRED exceeds the configured limit")
        return self


class BudgetUsage(_Model):
    """Derived from the selected items (validated against them)."""

    total: int = Field(ge=1)
    reserve: int = Field(ge=0)
    usable: int = Field(ge=1)
    used: int = Field(ge=0)
    remaining: int = Field(ge=0)
    overflow: int = Field(ge=0, description="used - usable when REQUIRED exceeds usable.")
    by_category: dict[BudgetCategory, int]
    files: int = Field(ge=0)
    adrs: int = Field(ge=0)
    memories: int = Field(ge=0)

    @classmethod
    def of(cls, limits: BudgetSection, selected: Sequence[BudgetedItem]) -> BudgetUsage:
        used = sum(item.included_size for item in selected)
        by_category = dict.fromkeys(BudgetCategory, 0)
        for item in selected:
            by_category[item.category] += item.included_size
        kinds = [item.candidate.kind for item in selected]
        return cls(
            total=limits.total, reserve=limits.reserve, usable=limits.usable, used=used,
            remaining=max(0, limits.usable - used), overflow=max(0, used - limits.usable),
            by_category=by_category, files=sum(1 for i in selected if is_file(i.candidate)),
            adrs=kinds.count(CandidateKind.ADR), memories=kinds.count(CandidateKind.MEMORY),
        )


def _status(not_selected: Sequence[BudgetedItem], usage: BudgetUsage) -> BudgetStatus:
    if any(i.classified.classification.classification is ContextClass.REQUIRED
           for i in not_selected):
        return BudgetStatus.REQUIRED_UNAVAILABLE
    if usage.overflow:
        return BudgetStatus.REQUIRED_OVERFLOW
    return BudgetStatus.SUCCESS


class ContextBudgetResult(_Model):
    """Every classified candidate in exactly one of `selected`, `not_selected`,
    `excluded`, each list in selection priority order. `limits` echoes the
    budget configuration used (unit, truncation, total, reserve, categories,
    max_*). `warnings`: discovery + classification warnings, then `budget:` ones."""

    request: EngineeringRequest
    status: BudgetStatus
    limits: BudgetSection
    usage: BudgetUsage
    selected: tuple[BudgetedItem, ...]
    not_selected: tuple[BudgetedItem, ...]
    excluded: tuple[BudgetedItem, ...]
    conflicts: tuple[LimitConflict, ...] = ()
    warnings: tuple[str, ...] = ()

    @classmethod
    def build(
        cls, request: EngineeringRequest, limits: BudgetSection, *,
        selected: Sequence[BudgetedItem], not_selected: Sequence[BudgetedItem],
        excluded: Sequence[BudgetedItem], conflicts: Sequence[LimitConflict] = (),
        warnings: Sequence[str] = (),
    ) -> ContextBudgetResult:
        usage = BudgetUsage.of(limits, selected)
        return cls(
            request=request, status=_status(not_selected, usage), limits=limits, usage=usage,
            selected=tuple(selected), not_selected=tuple(not_selected),
            excluded=tuple(excluded), conflicts=tuple(conflicts), warnings=tuple(warnings),
        )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for name, items, allowed in (
            ("selected", self.selected, SELECTED_REASONS),
            ("not_selected", self.not_selected, NOT_SELECTED_REASONS),
            ("excluded", self.excluded, EXCLUDED_REASONS),
        ):
            if any(item.reason not in allowed for item in items):
                raise ValueError(f"'{name}' holds an item with a reason of another list")
        ids = [i.candidate.id for i in (*self.selected, *self.not_selected, *self.excluded)]
        if len(set(ids)) != len(ids):
            raise ValueError("a candidate appears in more than one budget decision")
        if self.usage != BudgetUsage.of(self.limits, self.selected):
            raise ValueError("usage does not match the selected items")
        if self.status is not _status(self.not_selected, self.usage):
            raise ValueError("status does not match the items and usage")
        return self

    @property
    def items(self) -> tuple[BudgetedItem, ...]:
        return (*self.selected, *self.not_selected, *self.excluded)

"""`ContextBudgeter`: ContextClassificationResult -> ContextBudgetResult (V1.3).

    classified candidates, in selection priority (see `priority_key`)
      1. REQUIRED    load each; always selected (content missing -> not_selected
                     content_unavailable -> status REQUIRED_UNAVAILABLE). Never
                     limited: a REQUIRED set above a category/max_* limit is a
                     recorded conflict; above `usable` it is REQUIRED_OVERFLOW
      2. HIGH_VALUE  then OPTIONAL, one by one, whole items (first fit):
           REQUIRED overflowed ─────────────> required_overflow (not considered)
           max_adrs / max_files / max_memories reached ─> *_reached (never loaded)
           load content ──── failed ────────> content_unavailable
           size > usable or category limit ─> item_too_large
           size > usable remainder ─────────> total_budget_exhausted
           size > category remainder ───────> category_budget_exhausted
           else ────────────────────────────> selected, within_budget
         a skipped item does not stop the scan: a later, smaller item may fit
      3. EXCLUDED    never loaded, never selected, kept for audit

Priority inside a class uses signals classification already produced, never a
new judgement (no Jev, no LLM): deterministic before probabilistic before
fallback; probabilistic by decision confidence (higher first); then candidate
kind (library authority first ... memory last); then id (final tie-break).
Confidence never crosses classes: a HIGH_VALUE at 0.99 still comes after every
REQUIRED.

`build_budgeter(config, library)` is the composition step.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from orchestrator.config import BudgetSection, HarnessConfig
from orchestrator.context.budget.content import ContentLoader, ContextContentLoader
from orchestrator.context.budget.models import (
    CATEGORY_BY_KIND,
    BudgetCategory,
    BudgetedItem,
    BudgetReason,
    ContextBudgetResult,
    LimitConflict,
    LimitKind,
    is_file,
)
from orchestrator.context.classification.models import (
    CLASS_ORDER,
    ClassifiedContextCandidate,
    ContextClass,
    ContextClassificationResult,
    SelectedBy,
)
from orchestrator.context.discovery import project_files
from orchestrator.context.models import KIND_ORDER, CandidateKind
from orchestrator.library.library import GlobalLibrary

_SELECTOR_ORDER = {SelectedBy.DETERMINISTIC: 0, SelectedBy.PROBABILISTIC: 1,
                   SelectedBy.FALLBACK: 2}


def priority_key(item: ClassifiedContextCandidate) -> tuple[int, int, float, int, str]:
    """Selection order: class, who decided, confidence (probabilistic only), kind, id."""
    decision = item.classification
    confidence = (decision.confidence or 0.0) if (
        decision.selected_by is SelectedBy.PROBABILISTIC) else 0.0
    return (CLASS_ORDER[decision.classification], _SELECTOR_ORDER[decision.selected_by],
            -confidence, KIND_ORDER[item.candidate.kind], item.candidate.id)


@dataclass(slots=True)
class _Tally:
    """What the selected items use so far."""

    used: int = 0
    by_category: dict[BudgetCategory, int] = field(
        default_factory=lambda: dict.fromkeys(BudgetCategory, 0)
    )
    files: int = 0
    adrs: int = 0
    memories: int = 0

    def add(self, item: BudgetedItem) -> None:
        self.used += item.included_size
        self.by_category[item.category] += item.included_size
        self.files += is_file(item.candidate)
        self.adrs += item.candidate.kind is CandidateKind.ADR
        self.memories += item.candidate.kind is CandidateKind.MEMORY


class ContextBudgeter:
    def __init__(self, limits: BudgetSection, loader: ContentLoader) -> None:
        self._limits = limits
        self._loader = loader

    def budget(self, classified: ContextClassificationResult) -> ContextBudgetResult:
        ordered = sorted(classified.candidates, key=priority_key)
        tally = _Tally()
        selected: list[BudgetedItem] = []
        not_selected: list[BudgetedItem] = []

        for item in (c for c in ordered if _cls(c) is ContextClass.REQUIRED):
            loaded = self._loader.load(item.candidate)
            if loaded.text is None:
                not_selected.append(_item(item, BudgetReason.CONTENT_UNAVAILABLE,
                                          detail=loaded.problem or "no content"))
                continue
            chosen = _item(item, BudgetReason.REQUIRED, content=loaded.text)
            selected.append(chosen)
            tally.add(chosen)
        overflow = tally.used > self._limits.usable
        conflicts = self._conflicts(tally)

        for item in (c for c in ordered
                     if _cls(c) in (ContextClass.HIGH_VALUE, ContextClass.OPTIONAL)):
            decided = self._consider(item, tally, overflow=overflow)
            if decided.reason is BudgetReason.WITHIN_BUDGET:
                selected.append(decided)
                tally.add(decided)
            else:
                not_selected.append(decided)

        excluded = [_item(c, BudgetReason.EXCLUDED_BY_CLASSIFICATION)
                    for c in ordered if _cls(c) is ContextClass.EXCLUDED]
        return ContextBudgetResult.build(
            classified.request, self._limits, selected=selected, not_selected=not_selected,
            excluded=excluded, conflicts=conflicts,
            warnings=(*classified.warnings,
                      *self._warnings(tally, not_selected, conflicts, overflow=overflow)),
        )

    def _consider(self, item: ClassifiedContextCandidate, tally: _Tally, *,
                  overflow: bool) -> BudgetedItem:
        if overflow:
            return _item(item, BudgetReason.REQUIRED_OVERFLOW)
        if (limit := self._count_limit(item, tally)) is not None:
            return _item(item, limit)
        loaded = self._loader.load(item.candidate)  # lazy: only items still eligible
        if loaded.text is None:
            return _item(item, BudgetReason.CONTENT_UNAVAILABLE,
                         detail=loaded.problem or "no content")
        size = len(loaded.text)
        category = CATEGORY_BY_KIND[item.candidate.kind]
        cap = getattr(self._limits.categories, category.value)
        if size > self._limits.usable or (cap is not None and size > cap):
            return _item(item, BudgetReason.ITEM_TOO_LARGE, size=size)
        if size > self._limits.usable - tally.used:
            return _item(item, BudgetReason.TOTAL_BUDGET_EXHAUSTED, size=size)
        if cap is not None and size > cap - tally.by_category[category]:
            return _item(item, BudgetReason.CATEGORY_BUDGET_EXHAUSTED, size=size)
        return _item(item, BudgetReason.WITHIN_BUDGET, content=loaded.text)

    def _count_limit(self, item: ClassifiedContextCandidate,
                     tally: _Tally) -> BudgetReason | None:
        kind = item.candidate.kind
        limits = self._limits
        if kind is CandidateKind.MEMORY and tally.memories >= limits.max_memories:
            return BudgetReason.MAX_MEMORIES_REACHED
        if kind is CandidateKind.ADR and tally.adrs >= limits.max_adrs:
            return BudgetReason.MAX_ADRS_REACHED
        if is_file(item.candidate) and tally.files >= limits.max_files:
            return BudgetReason.MAX_FILES_REACHED
        return None

    def _conflicts(self, required: _Tally) -> list[LimitConflict]:
        """Limits the REQUIRED items alone exceed (kept, never enforced on them)."""
        limits = self._limits
        conflicts = [
            LimitConflict(limit=LimitKind.CATEGORY, category=category, configured=cap,
                          required=required.by_category[category])
            for category in BudgetCategory
            if (cap := getattr(limits.categories, category.value)) is not None
            and required.by_category[category] > cap
        ]
        for kind, configured, used in (
            (LimitKind.MAX_FILES, limits.max_files, required.files),
            (LimitKind.MAX_ADRS, limits.max_adrs, required.adrs),
            (LimitKind.MAX_MEMORIES, limits.max_memories, required.memories),
        ):
            if used > configured:
                conflicts.append(LimitConflict(limit=kind, configured=configured, required=used))
        return conflicts

    def _warnings(self, tally: _Tally, not_selected: Sequence[BudgetedItem],
                  conflicts: Sequence[LimitConflict], *, overflow: bool) -> list[str]:
        warnings = [
            f"budget: REQUIRED '{i.candidate.id}' has no loadable content: {i.detail}"
            for i in not_selected if _cls(i.classified) is ContextClass.REQUIRED
        ]
        if overflow:
            warnings.append(
                f"budget: REQUIRED context ({tally.used} characters) exceeds the usable budget "
                f"({self._limits.usable}) by {tally.used - self._limits.usable}; nothing else "
                "was considered and nothing REQUIRED was removed"
            )
        warnings.extend(
            f"budget: REQUIRED items exceed {c.limit}"
            f"{f' {c.category}' if c.category else ''} ({c.required} > {c.configured}); "
            "kept (REQUIRED is never limited)"
            for c in conflicts
        )
        return warnings


def _cls(item: ClassifiedContextCandidate) -> ContextClass:
    return item.classification.classification


def _item(item: ClassifiedContextCandidate, reason: BudgetReason, *, content: str | None = None,
          size: int | None = None, detail: str | None = None) -> BudgetedItem:
    if content is not None:
        size = len(content)
    return BudgetedItem(
        classified=item, category=CATEGORY_BY_KIND[item.candidate.kind], reason=reason,
        size=size, included_size=len(content) if content is not None else 0, detail=detail,
        content=content,
    )


def build_budgeter(config: HarnessConfig, library: GlobalLibrary) -> ContextBudgeter:
    """Compose the budgeter for `config` (context.yaml `budget`): the same
    ProjectFiles rules as discovery, and the library that discovery used."""
    return ContextBudgeter(config.context.budget,
                           ContextContentLoader(project_files(config), library))

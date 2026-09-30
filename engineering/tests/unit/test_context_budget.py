"""V1.3 Context Budget: selection policy (offline, fake content loader).

REQUIRED always -> HIGH_VALUE -> OPTIONAL (first fit, whole items) -> EXCLUDED never;
limits (total, reserve, category, max_*); ordering; determinism; audit trail."""

from __future__ import annotations

import pytest
from budget_helpers import FakeLoader, classified, ids, item, limits, reasons, run
from classification_helpers import request

from orchestrator.context.budget.budgeter import ContextBudgeter, priority_key
from orchestrator.context.budget.models import (
    BudgetCategory,
    BudgetReason,
    BudgetStatus,
    LimitConflict,
    LimitKind,
)
from orchestrator.context.classification.models import ContextClass, SelectedBy
from orchestrator.context.models import CandidateKind

K = CandidateKind
REQ, HIGH, OPT, EXC = (ContextClass.REQUIRED, ContextClass.HIGH_VALUE, ContextClass.OPTIONAL,
              ContextClass.EXCLUDED)

# --- REQUIRED -----------------------------------------------------------------------------------


def test_all_required_fit_and_are_selected() -> None:
    result, _ = run(limits(1000), {"source/a.py": 300, "instructions/AGENTS.md": 200},
                    item(K.SOURCE_CODE, "a.py", REQ),
                    item(K.PROJECT_INSTRUCTIONS, "AGENTS.md", REQ))
    assert result.status is BudgetStatus.SUCCESS
    assert ids(result.selected) == ["instructions/AGENTS.md", "source/a.py"]
    assert {i.reason for i in result.selected} == {BudgetReason.REQUIRED}
    assert (result.usage.used, result.usage.remaining, result.usage.overflow) == (500, 500, 0)


def test_required_exactly_filling_the_budget_is_success() -> None:
    result, _ = run(limits(1000, reserve=200), {"source/a.py": 800},
                    item(K.SOURCE_CODE, "a.py", REQ))
    assert result.status is BudgetStatus.SUCCESS
    assert (result.usage.usable, result.usage.used, result.usage.remaining) == (800, 800, 0)


def test_required_total_over_usable_is_overflow_and_nothing_required_is_removed() -> None:
    result, loader = run(
        limits(1000, reserve=200), {"source/a.py": 500, "source/b.py": 500, "guideline/g": 10},
        item(K.SOURCE_CODE, "a.py", REQ), item(K.SOURCE_CODE, "b.py", REQ),
        item(K.GUIDELINE, "g", HIGH),
    )
    assert result.status is BudgetStatus.REQUIRED_OVERFLOW
    assert ids(result.selected) == ["source/a.py", "source/b.py"]
    assert (result.usage.used, result.usage.remaining, result.usage.overflow) == (1000, 0, 200)
    assert reasons(result)["guideline/g"] == "required_overflow"
    assert "guideline/g" not in loader.loaded  # not even considered
    assert any("exceeds the usable budget (800) by 200" in w for w in result.warnings)


def test_a_single_required_larger_than_usable_is_overflow_not_truncated() -> None:
    result, _ = run(limits(1000, reserve=100), {"doc/big.md": 950},
                    item(K.DOCUMENTATION, "big.md", REQ))
    assert result.status is BudgetStatus.REQUIRED_OVERFLOW
    (big,) = result.selected
    assert (big.size, big.included_size, len(big.content or "")) == (950, 950, 950)


def test_required_is_not_limited_by_max_files_and_the_conflict_is_explicit() -> None:
    result, _ = run(limits(1000, max_files=1),
                    {"source/a.py": 10, "source/b.py": 10, "source/c.py": 10},
                    item(K.SOURCE_CODE, "a.py", REQ), item(K.SOURCE_CODE, "b.py", REQ),
                    item(K.SOURCE_CODE, "c.py", HIGH))
    assert ids(result.selected) == ["source/a.py", "source/b.py"]
    assert reasons(result)["source/c.py"] == "max_files_reached"
    assert result.status is BudgetStatus.SUCCESS
    assert result.conflicts == (LimitConflict(limit=LimitKind.MAX_FILES, configured=1,
                                              required=2),)
    assert any("REQUIRED items exceed max_files (2 > 1)" in w for w in result.warnings)


def test_required_is_not_limited_by_category_or_max_adrs() -> None:
    result, _ = run(limits(1000, categories={"adrs": 50}, max_adrs=1),
                    {"adr/1.md": 40, "adr/2.md": 40},
                    item(K.ADR, "1.md", REQ), item(K.ADR, "2.md", REQ))
    assert ids(result.selected) == ["adr/1.md", "adr/2.md"]
    assert {(c.limit, c.category, c.configured, c.required) for c in result.conflicts} == {
        (LimitKind.CATEGORY, BudgetCategory.ADRS, 50, 80), (LimitKind.MAX_ADRS, None, 1, 2),
    }


def test_required_policies_and_instructions_survive_a_tight_budget() -> None:
    result, _ = run(
        limits(300), {"policy/secrets": 100, "policy/git": 100, "instructions/CLAUDE.md": 100,
                      "guideline/coding": 1},
        item(K.POLICY, "secrets", REQ), item(K.POLICY, "git", REQ),
        item(K.PROJECT_INSTRUCTIONS, "CLAUDE.md", REQ), item(K.GUIDELINE, "coding", HIGH),
    )
    assert ids(result.selected) == ["policy/git", "policy/secrets", "instructions/CLAUDE.md"]
    assert reasons(result)["guideline/coding"] == "total_budget_exhausted"
    assert result.status is BudgetStatus.SUCCESS


def test_required_without_content_is_required_unavailable_never_silently_dropped() -> None:
    result, _ = run(limits(1000), {"source/a.py": 10},
                    item(K.SOURCE_CODE, "a.py", REQ), item(K.SOURCE_CODE, "logo.png", REQ))
    assert result.status is BudgetStatus.REQUIRED_UNAVAILABLE
    (missing,) = result.not_selected
    assert (missing.candidate.id, missing.reason) == ("source/logo.png",
                                                      BudgetReason.CONTENT_UNAVAILABLE)
    assert missing.detail == "no text for source/logo.png"
    assert any("REQUIRED 'source/logo.png' has no loadable content" in w for w in result.warnings)


def test_required_unavailable_takes_precedence_over_overflow() -> None:
    result, _ = run(limits(100), {"source/a.py": 200},
                    item(K.SOURCE_CODE, "a.py", REQ), item(K.SOURCE_CODE, "gone.py", REQ))
    assert result.status is BudgetStatus.REQUIRED_UNAVAILABLE
    assert result.usage.overflow == 100  # still reported


# --- HIGH_VALUE / OPTIONAL ----------------------------------------------------------------------


def test_high_value_is_selected_before_optional_whatever_their_kind_or_id() -> None:
    result, _ = run(limits(100), {"policy/aaa": 100, "source/zzz.py": 100},
                    item(K.POLICY, "aaa", OPT), item(K.SOURCE_CODE, "zzz.py", HIGH))
    assert ids(result.selected) == ["source/zzz.py"]
    assert reasons(result)["policy/aaa"] == "total_budget_exhausted"


def test_high_value_items_follow_a_deterministic_order() -> None:
    result, _ = run(limits(1000), {"source/b.py": 1, "source/a.py": 1, "skill/python": 1,
                                   "guideline/testing": 1},
                    item(K.SOURCE_CODE, "b.py", HIGH), item(K.SOURCE_CODE, "a.py", HIGH),
                    item(K.SKILL, "python", HIGH), item(K.GUIDELINE, "testing", HIGH))
    assert ids(result.selected) == ["guideline/testing", "skill/python", "source/a.py",
                                    "source/b.py"]


def test_a_large_item_that_does_not_fit_does_not_block_smaller_later_items() -> None:
    result, _ = run(limits(100), {"source/a.py": 60, "source/b.py": 50, "source/c.py": 40},
                    item(K.SOURCE_CODE, "a.py", HIGH), item(K.SOURCE_CODE, "b.py", HIGH),
                    item(K.SOURCE_CODE, "c.py", HIGH))
    assert ids(result.selected) == ["source/a.py", "source/c.py"]
    b = result.not_selected[0]
    assert (b.candidate.id, b.reason, b.size, b.included_size, b.content) == (
        "source/b.py", BudgetReason.TOTAL_BUDGET_EXHAUSTED, 50, 0, None)


def test_an_item_larger_than_usable_is_item_too_large() -> None:
    result, _ = run(limits(100, reserve=10), {"doc/big.md": 95},
                    item(K.DOCUMENTATION, "big.md", HIGH))
    assert reasons(result) == {"doc/big.md": "item_too_large"}
    assert result.not_selected[0].size == 95


def test_optional_only_uses_what_required_and_high_value_leave() -> None:
    result, _ = run(limits(100), {"source/r.py": 50, "source/h.py": 30, "doc/o1.md": 30,
                                  "doc/o2.md": 20},
                    item(K.DOCUMENTATION, "o1.md", OPT), item(K.DOCUMENTATION, "o2.md", OPT),
                    item(K.SOURCE_CODE, "h.py", HIGH), item(K.SOURCE_CODE, "r.py", REQ))
    assert ids(result.selected) == ["source/r.py", "source/h.py", "doc/o2.md"]
    assert reasons(result)["doc/o1.md"] == "total_budget_exhausted"


def test_fallback_optional_is_treated_as_any_optional_and_never_promoted() -> None:
    fallback = item(K.DOCUMENTATION, "f.md", OPT, by=SelectedBy.FALLBACK)
    result, _ = run(limits(100), {"doc/f.md": 10}, fallback)
    (chosen,) = result.selected
    assert chosen.reason is BudgetReason.WITHIN_BUDGET
    assert chosen.classified == fallback  # class and selector untouched: still OPTIONAL


# --- EXCLUDED -----------------------------------------------------------------------------------


def test_excluded_is_never_selected_nor_loaded_and_stays_auditable() -> None:
    excluded = item(K.SOURCE_CODE, "uv.lock", EXC)
    result, loader = run(limits(10_000), {"source/uv.lock": 1}, excluded)
    assert result.selected == () and result.not_selected == ()
    (kept,) = result.excluded
    assert kept.reason is BudgetReason.EXCLUDED_BY_CLASSIFICATION
    assert kept.classified == excluded  # the classification reason is preserved
    assert kept.size is None and loader.loaded == []


# --- limits -------------------------------------------------------------------------------------


def test_reserve_is_not_usable() -> None:
    result, _ = run(limits(100, reserve=40),
                    {"source/a.py": 50, "source/b.py": 61, "source/c.py": 11},
                    item(K.SOURCE_CODE, "a.py", HIGH), item(K.SOURCE_CODE, "b.py", HIGH),
                    item(K.SOURCE_CODE, "c.py", HIGH))
    assert ids(result.selected) == ["source/a.py"]
    assert reasons(result)["source/b.py"] == "item_too_large"  # fits total 100, not usable 60
    assert reasons(result)["source/c.py"] == "total_budget_exhausted"  # 11 > 60 - 50
    assert (result.usage.total, result.usage.reserve, result.usage.usable) == (100, 40, 60)


def test_category_limit() -> None:
    result, _ = run(limits(1000, categories={"documentation": 50}),
                    {"doc/a.md": 30, "doc/b.md": 30, "doc/c.md": 60, "source/s.py": 30},
                    item(K.DOCUMENTATION, "a.md", HIGH), item(K.DOCUMENTATION, "b.md", HIGH),
                    item(K.DOCUMENTATION, "c.md", HIGH), item(K.SOURCE_CODE, "s.py", HIGH))
    assert reasons(result) == {
        "doc/a.md": "within_budget", "source/s.py": "within_budget",
        "doc/b.md": "category_budget_exhausted", "doc/c.md": "item_too_large",
    }
    assert result.usage.by_category[BudgetCategory.DOCUMENTATION] == 30


def test_required_usage_counts_toward_a_category_limit() -> None:
    result, _ = run(limits(1000, categories={"source_code": 100}),
                    {"source/r.py": 90, "source/h.py": 20},
                    item(K.SOURCE_CODE, "r.py", REQ), item(K.SOURCE_CODE, "h.py", HIGH))
    assert reasons(result)["source/h.py"] == "category_budget_exhausted"
    assert result.conflicts == ()


def test_max_files_counts_project_files_not_library_artifacts() -> None:
    result, loader = run(limits(1000, max_files=1),
                         {"source/a.py": 1, "doc/b.md": 1, "skill/python": 1},
                         item(K.SOURCE_CODE, "a.py", HIGH), item(K.DOCUMENTATION, "b.md", HIGH),
                         item(K.SKILL, "python", HIGH))
    assert reasons(result) == {"skill/python": "within_budget", "doc/b.md": "within_budget",
                               "source/a.py": "max_files_reached"}
    assert "source/a.py" not in loader.loaded  # count limits are checked before loading
    assert result.usage.files == 1


def test_max_adrs_before_max_files_and_adrs_are_files() -> None:
    result, _ = run(limits(1000, max_adrs=1, max_files=2),
                    {"adr/1.md": 1, "adr/2.md": 1, "doc/d.md": 1, "source/s.py": 1},
                    item(K.ADR, "1.md", HIGH), item(K.ADR, "2.md", HIGH),
                    item(K.DOCUMENTATION, "d.md", HIGH), item(K.SOURCE_CODE, "s.py", HIGH))
    assert reasons(result) == {"adr/1.md": "within_budget", "adr/2.md": "max_adrs_reached",
                               "doc/d.md": "within_budget", "source/s.py": "max_files_reached"}
    assert (result.usage.files, result.usage.adrs) == (2, 1)


def test_max_memories() -> None:
    result, _ = run(limits(1000, max_memories=1), {"memory/m1": 5, "memory/m2": 5},
                    item(K.MEMORY, "m1", OPT), item(K.MEMORY, "m2", OPT))
    assert reasons(result) == {"memory/m1": "within_budget", "memory/m2": "max_memories_reached"}
    assert result.usage.memories == 1


def test_zero_limits_select_nothing_but_required() -> None:
    result, _ = run(limits(1000, max_files=0, max_memories=0),
                    {"source/r.py": 5, "source/h.py": 5, "memory/m": 5},
                    item(K.SOURCE_CODE, "r.py", REQ), item(K.SOURCE_CODE, "h.py", HIGH),
                    item(K.MEMORY, "m", OPT))
    assert ids(result.selected) == ["source/r.py"]
    assert result.conflicts[0].limit is LimitKind.MAX_FILES


def test_memory_never_displaces_required_official_context() -> None:
    result, _ = run(limits(100), {"policy/secrets": 60, "source/a.py": 40, "memory/m": 10},
                    item(K.MEMORY, "m", OPT), item(K.POLICY, "secrets", REQ),
                    item(K.SOURCE_CODE, "a.py", REQ))
    assert ids(result.selected) == ["policy/secrets", "source/a.py"]
    assert reasons(result)["memory/m"] == "total_budget_exhausted"


def test_optional_content_unavailable_is_recorded_and_the_scan_goes_on() -> None:
    result, _ = run(limits(100), {"doc/b.md": 10},
                    item(K.DOCUMENTATION, "a.md", OPT), item(K.DOCUMENTATION, "b.md", OPT))
    assert reasons(result) == {"doc/b.md": "within_budget", "doc/a.md": "content_unavailable"}
    assert result.status is BudgetStatus.SUCCESS


# --- ordering and determinism -------------------------------------------------------------------


def test_deterministic_before_probabilistic_by_confidence_then_id() -> None:
    items = (
        item(K.SOURCE_CODE, "p75.py", HIGH, by=SelectedBy.PROBABILISTIC, confidence=0.75),
        item(K.SOURCE_CODE, "p95.py", HIGH, by=SelectedBy.PROBABILISTIC, confidence=0.95),
        item(K.SOURCE_CODE, "z-rule.py", HIGH),
        item(K.SOURCE_CODE, "b-p95.py", HIGH, by=SelectedBy.PROBABILISTIC, confidence=0.95),
    )
    ordered = sorted(items, key=priority_key)
    assert [i.candidate.id for i in ordered] == [
        "source/z-rule.py", "source/b-p95.py", "source/p95.py", "source/p75.py",
    ]


def test_confidence_never_crosses_classes() -> None:
    confident = item(K.GUIDELINE, "g", HIGH, by=SelectedBy.PROBABILISTIC, confidence=0.99)
    result, _ = run(limits(50), {"guideline/g": 10, "source/z.py": 50},
                    confident, item(K.SOURCE_CODE, "z.py", REQ))
    assert ids(result.selected) == ["source/z.py"]
    assert reasons(result)["guideline/g"] == "total_budget_exhausted"


def test_probabilistic_optional_before_fallback_optional() -> None:
    result, _ = run(limits(10), {"doc/a.md": 10, "doc/b.md": 10},
                    item(K.DOCUMENTATION, "a.md", OPT, by=SelectedBy.FALLBACK),
                    item(K.DOCUMENTATION, "b.md", OPT, by=SelectedBy.PROBABILISTIC))
    assert ids(result.selected) == ["doc/b.md"]


def test_result_is_deterministic_and_independent_of_input_order() -> None:
    items = [item(K.SOURCE_CODE, f"{n}.py", cls) for n, cls in
             (("a", HIGH), ("b", OPT), ("c", REQ), ("d", EXC), ("e", HIGH), ("f", OPT))]
    sizes = {f"source/{n}.py": 30 for n in "abcdef"}
    subject = request()
    first, second = (
        ContextBudgeter(limits(100), FakeLoader(sizes)).budget(classified(*order, subject=subject))
        for order in (items, items[::-1])
    )
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert ids(first.selected) == ["source/c.py", "source/a.py", "source/e.py"]


def test_every_candidate_gets_exactly_one_decision_with_both_reasons() -> None:
    items = (item(K.SOURCE_CODE, "r.py", REQ), item(K.SOURCE_CODE, "h.py", HIGH),
             item(K.DOCUMENTATION, "o.md", OPT), item(K.SOURCE_CODE, "x.lock", EXC))
    source = classified(*items)
    result = ContextBudgeter(limits(40), FakeLoader({"source/r.py": 30, "source/h.py": 20,
                                                     "doc/o.md": 5})).budget(source)
    assert sorted(ids(result.items)) == sorted(c.candidate.id for c in source.candidates)
    for budgeted in result.items:
        original = next(c for c in source.candidates if c.candidate.id == budgeted.candidate.id)
        assert budgeted.classified == original  # classification reason kept, not overwritten
        assert isinstance(budgeted.reason, BudgetReason)
    assert result.request == source.request


def test_classification_warnings_are_kept() -> None:
    source = classified(item(K.SOURCE_CODE, "a.py", HIGH)).model_copy(
        update={"warnings": ("classification: something",)})
    result = ContextBudgeter(limits(), FakeLoader({"source/a.py": 1})).budget(source)
    assert result.warnings == ("classification: something",)


@pytest.mark.parametrize("cls", [HIGH, OPT])
def test_selected_items_carry_their_content(cls: ContextClass) -> None:
    result, _ = run(limits(), {"doc/a.md": "héllo"}, item(K.DOCUMENTATION, "a.md", cls))
    (chosen,) = result.selected
    assert (chosen.content, chosen.size, chosen.included_size) == ("héllo", 5, 5)

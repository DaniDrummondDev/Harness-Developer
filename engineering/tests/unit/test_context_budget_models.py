"""V1.3 Context Budget: contracts, invariants, configuration and the doctor check."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from budget_helpers import item, limits, run
from pydantic import ValidationError

from orchestrator.config import BudgetSection, CategoryLimits, default_harness_root, load_config
from orchestrator.context.budget.content import ContextContentLoader
from orchestrator.context.budget.models import (
    CATEGORY_BY_KIND,
    BudgetCategory,
    BudgetedItem,
    BudgetReason,
    BudgetStatus,
    BudgetUsage,
    ContextBudgetResult,
    LimitConflict,
    LimitKind,
)
from orchestrator.context.classification.models import ContextClass
from orchestrator.context.models import CandidateKind
from orchestrator.core.exceptions import ConfigValidationError
from orchestrator.doctor import CheckStatus, check_budget, run_doctor
from orchestrator.utils.shell import CommandResult

K = CandidateKind
REQ, HIGH, OPT, EXC = (ContextClass.REQUIRED, ContextClass.HIGH_VALUE, ContextClass.OPTIONAL,
              ContextClass.EXCLUDED)
WriteConfig = Callable[[str, str], Path]

# --- vocabulary ---------------------------------------------------------------------------------


def test_exact_status_and_categories() -> None:
    assert [s.value for s in BudgetStatus] == ["SUCCESS", "REQUIRED_OVERFLOW",
                                               "REQUIRED_UNAVAILABLE"]
    assert [c.value for c in BudgetCategory] == ["library", "instructions", "adrs",
                                                 "documentation", "source_code", "memory"]


def test_every_candidate_kind_has_a_category_and_config_has_every_category() -> None:
    assert set(CATEGORY_BY_KIND) == set(CandidateKind)
    assert set(CategoryLimits.model_fields) == {c.value for c in BudgetCategory}


def test_budget_does_not_add_classes() -> None:
    assert [c.value for c in ContextClass] == ["REQUIRED", "HIGH_VALUE", "OPTIONAL", "EXCLUDED"]


# --- BudgetedItem invariants --------------------------------------------------------------------


def _budgeted(cls: ContextClass, reason: BudgetReason, **fields: Any) -> BudgetedItem:
    return BudgetedItem(classified=item(K.SOURCE_CODE, "a.py", cls),
                        category=BudgetCategory.SOURCE_CODE, reason=reason, **fields)


@pytest.mark.parametrize("reason", [BudgetReason.WITHIN_BUDGET,
                                    BudgetReason.TOTAL_BUDGET_EXHAUSTED,
                                    BudgetReason.MAX_FILES_REACHED,
                                    BudgetReason.REQUIRED_OVERFLOW])
def test_required_cannot_be_left_out_or_selected_for_budget_reasons(reason: BudgetReason) -> None:
    content = {"content": "x", "size": 1, "included_size": 1} if reason is (
        BudgetReason.WITHIN_BUDGET) else {}
    with pytest.raises(ValidationError, match="REQUIRED"):
        _budgeted(REQ, reason, **content)


def test_only_required_is_selected_as_required() -> None:
    with pytest.raises(ValidationError, match="REQUIRED"):
        _budgeted(HIGH, BudgetReason.REQUIRED, content="x", size=1, included_size=1)


def test_excluded_only_as_excluded_by_classification() -> None:
    with pytest.raises(ValidationError, match="EXCLUDED"):
        _budgeted(EXC, BudgetReason.WITHIN_BUDGET, content="x", size=1, included_size=1)
    with pytest.raises(ValidationError, match="EXCLUDED"):
        _budgeted(HIGH, BudgetReason.EXCLUDED_BY_CLASSIFICATION)
    assert _budgeted(EXC, BudgetReason.EXCLUDED_BY_CLASSIFICATION).size is None


@pytest.mark.parametrize("fields", [
    {},  # no content
    {"content": "abc", "size": 2, "included_size": 2},  # size mismatch
    {"content": "abc", "size": 3, "included_size": 1},  # truncation is not allowed
])
def test_selected_item_carries_exact_whole_content(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _budgeted(HIGH, BudgetReason.WITHIN_BUDGET, **fields)


def test_not_selected_item_has_no_content_and_detail_only_when_unavailable() -> None:
    with pytest.raises(ValidationError, match="no content"):
        _budgeted(HIGH, BudgetReason.TOTAL_BUDGET_EXHAUSTED, size=3, content="abc")
    with pytest.raises(ValidationError, match="detail"):
        _budgeted(HIGH, BudgetReason.CONTENT_UNAVAILABLE)
    with pytest.raises(ValidationError, match="detail"):
        _budgeted(HIGH, BudgetReason.ITEM_TOO_LARGE, size=3, detail="why")
    assert _budgeted(REQ, BudgetReason.CONTENT_UNAVAILABLE, detail="binary").detail == "binary"


def test_category_must_match_the_kind() -> None:
    with pytest.raises(ValidationError, match="category"):
        BudgetedItem(classified=item(K.SOURCE_CODE, "a.py", HIGH), category=BudgetCategory.MEMORY,
                     reason=BudgetReason.ITEM_TOO_LARGE, size=1)


def test_limit_conflict_invariants() -> None:
    with pytest.raises(ValidationError, match="exceeds"):
        LimitConflict(limit=LimitKind.MAX_FILES, configured=2, required=2)
    with pytest.raises(ValidationError, match="category"):
        LimitConflict(limit=LimitKind.CATEGORY, configured=1, required=2)
    with pytest.raises(ValidationError, match="category"):
        LimitConflict(limit=LimitKind.MAX_ADRS, category=BudgetCategory.ADRS, configured=1,
                      required=2)


# --- result invariants and serialization --------------------------------------------------------


def _sample() -> ContextBudgetResult:
    result, _ = run(limits(100, reserve=20, categories={"documentation": 10}),
                    {"source/r.py": 30, "doc/h.md": 20, "memory/m": 5},
                    item(K.SOURCE_CODE, "r.py", REQ), item(K.DOCUMENTATION, "h.md", HIGH),
                    item(K.MEMORY, "m", OPT), item(K.SOURCE_CODE, "x.lock", EXC))
    return result


def test_usage_is_derived_from_the_selected_items() -> None:
    usage = _sample().usage
    assert usage == BudgetUsage(
        total=100, reserve=20, usable=80, used=35, remaining=45, overflow=0,
        by_category={**dict.fromkeys(BudgetCategory, 0), BudgetCategory.SOURCE_CODE: 30,
                     BudgetCategory.MEMORY: 5},
        files=1, adrs=0, memories=1,
    )


def test_round_trip_json() -> None:
    result = _sample()
    again = ContextBudgetResult.model_validate_json(result.model_dump_json())
    assert again == result
    data = result.model_dump(mode="json")
    assert data["status"] == "SUCCESS"
    assert data["limits"]["unit"] == "characters"
    assert data["limits"]["truncation"] == "whole_item"
    assert [i["reason"] for i in data["not_selected"]] == ["item_too_large"]
    assert data["excluded"][0]["classified"]["classification"]["evidence"] == "generated_artifact"


@pytest.mark.parametrize("change", ["usage", "status", "list", "duplicate"])
def test_inconsistent_results_are_rejected(change: str) -> None:
    result = _sample()
    data = result.model_dump()
    if change == "usage":
        data["usage"]["used"] = 1
    elif change == "status":
        data["status"] = BudgetStatus.REQUIRED_OVERFLOW
    elif change == "list":
        data["selected"], data["not_selected"] = data["not_selected"], data["selected"]
    else:
        data["excluded"] = [*data["excluded"], data["excluded"][0]]
    with pytest.raises(ValidationError):
        ContextBudgetResult.model_validate(data)


def test_result_items_are_immutable() -> None:
    result = _sample()
    with pytest.raises(ValidationError):
        result.selected[0].reason = BudgetReason.WITHIN_BUDGET  # type: ignore[misc]


# --- configuration ------------------------------------------------------------------------------


def test_shipped_budget_config() -> None:
    budget = load_config(default_harness_root()).context.budget
    assert (budget.unit, budget.truncation) == ("characters", "whole_item")
    assert (budget.total, budget.reserve, budget.usable) == (100_000, 20_000, 80_000)
    assert budget.categories == CategoryLimits(library=20_000, adrs=15_000, documentation=25_000,
                                               source_code=40_000, memory=2_000)
    assert (budget.max_files, budget.max_adrs, budget.max_memories) == (20, 5, 5)


def test_budget_section_defaults(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext:\n  enabled: true\n")
    assert load_config(harness_root).context.budget == BudgetSection()
    assert BudgetSection().usable == 80_000


@pytest.mark.parametrize(("budget", "message"), [
    ("{total: 0}", "greater than or equal to 1"),
    ("{reserve: -1}", "greater than or equal to 0"),
    ("{total: 100, reserve: 100}", "reserve \\(100\\) must be smaller than total"),
    ("{total: 100, reserve: 150}", "must be smaller"),
    ("{categories: {memory: -1}}", "greater than or equal to 0"),
    ("{categories: {policies: 10}}", "Extra inputs"),
    ("{max_files: -1}", "greater than or equal to 0"),
    ("{max_adrs: -1}", "greater than or equal to 0"),
    ("{max_memories: -1}", "greater than or equal to 0"),
    ("{unit: tokens}", "characters"),
    ("{truncation: head}", "whole_item"),
    ("{enabled: true}", "Extra inputs"),
    ("{max_tokens: 10}", "Extra inputs"),
])
def test_invalid_budget_config_fails_early(harness_root: Path, write_config: WriteConfig,
                                           budget: str, message: str) -> None:
    write_config("context.yaml", f"version: 1\ncontext:\n  enabled: true\n  budget: {budget}\n")
    with pytest.raises(ConfigValidationError, match=message):
        load_config(harness_root)


def test_zero_limits_are_valid(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext:\n  budget: {max_files: 0, max_adrs: 0, "
                                 "max_memories: 0, categories: {memory: 0}}\n")
    budget = load_config(harness_root).context.budget
    assert (budget.max_files, budget.categories.memory) == (0, 0)


# --- doctor -------------------------------------------------------------------------------------


def _git_ok(args: object, *, cwd: Path | None = None, timeout: float | None = None
            ) -> CommandResult:
    return CommandResult(("git",), cwd, 0, "true\n", "", 0.0)


def _doctor(harness_root: Path) -> dict[str, tuple[CheckStatus, str]]:
    report = run_doctor(harness_root, environ={}, runner=_git_ok, python_version=(3, 12, 0))
    return {r.name: (r.status, r.detail) for r in report.results}


def test_doctor_budget_reports_the_shipped_budget(harness_root: Path) -> None:
    status, detail = _doctor(harness_root)["budget"]
    assert status is CheckStatus.PASS
    assert "characters, whole_item: total 100000 - reserve 20000 = usable 80000" in detail
    assert "source_code 40000" in detail and "max_memories 5" in detail


def test_doctor_warns_on_a_category_limit_that_never_binds(harness_root: Path,
                                                           write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext:\n  enabled: true\n  budget: "
                                 "{total: 1000, reserve: 100, categories: {memory: 900}}\n")
    status, detail = _doctor(harness_root)["budget"]
    assert status is CheckStatus.WARN
    assert "never binding: memory" in detail


def test_doctor_budget_is_structural(harness_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("doctor must not load context content")

    monkeypatch.setattr(ContextContentLoader, "load", forbidden)
    assert _doctor(harness_root)["budget"][0] is CheckStatus.PASS


def test_doctor_skips_budget_when_context_is_disabled(harness_root: Path,
                                                      write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext: {enabled: false}\n")
    assert "budget" not in _doctor(harness_root)


def test_check_budget_without_category_limits() -> None:
    config = load_config(default_harness_root())
    bare = config.model_copy(update={"context": config.context.model_copy(
        update={"budget": BudgetSection()})})
    result = check_budget(bare)
    assert (result.status, "categories none" in result.detail) == (CheckStatus.PASS, True)

"""V1.4 ContextPlan: planner call through LLMProvider, strict output validation,
deterministic invariants, provider failure fallback and input safety."""

from __future__ import annotations

import json

import pytest
from budget_helpers import item, limits
from classification_helpers import candidate
from escalation_helpers import (
    ScriptedLLMProvider,
    budget_of,
    escalate,
    plan_json,
    prompt_input,
)
from pydantic import ValidationError

from orchestrator.context.budget.models import BudgetReason, ContextBudgetResult
from orchestrator.context.classification.models import (
    ClassifiedContextCandidate,
    ContextClass,
    ContextClassification,
    Evidence,
    SelectedBy,
)
from orchestrator.context.escalation.models import (
    ConstraintKind,
    ContextEscalationResult,
    ContextPlan,
    PlanningFailure,
    PlanStatus,
)
from orchestrator.context.models import CandidateKind
from orchestrator.core.exceptions import ProviderCallError, ProviderError

R = ContextClass.REQUIRED
H = ContextClass.HIGH_VALUE
O = ContextClass.OPTIONAL  # noqa: E741
X = ContextClass.EXCLUDED
SRC = CandidateKind.SOURCE_CODE
DOC = CandidateKind.DOCUMENTATION

POLICY, CODE, OTHER, DOCS, LOCK = (
    "policy/secrets", "source/src/a.py", "source/src/b.py", "doc/docs/x.md", "source/yarn.lock")
MARKER = "CONTENT-MUST-NEVER-LEAVE"


def items() -> list[ClassifiedContextCandidate]:
    return [item(CandidateKind.POLICY, "secrets", R), item(SRC, "src/a.py", R),
            item(SRC, "src/b.py", H), item(DOC, "docs/x.md", O), item(SRC, "yarn.lock", X)]


def sized(n: int) -> str:
    return (MARKER + "x" * n)[:n] if n >= len(MARKER) else "x" * n


def budget(total: int = 1000, **sizes: int) -> ContextBudgetResult:
    """intent plan -> ARCHITECTURAL_TASK fires; sizes 20 each unless given."""
    base = {POLICY: 20, CODE: 20, OTHER: 20, DOCS: 20} | {
        k.replace("__", "/"): v for k, v in sizes.items()}
    return budget_of({k: sized(v) for k, v in base.items()}, *items(),
                     budget=limits(total=total), intent="plan")


def run(answer: str, *, total: int = 1000) -> tuple[ContextEscalationResult, ScriptedLLMProvider]:
    llm = ScriptedLLMProvider(answer)
    return escalate(budget(total), llm), llm


# --- valid plans -------------------------------------------------------------------------------


def test_valid_plan_is_planned_with_call_metadata() -> None:
    result, llm = run(plan_json([POLICY, CODE, DOCS]))
    assert result.status is PlanStatus.PLANNED and result.llm_calls == 1
    plan = result.plan
    assert plan is not None
    assert plan.selected_candidate_ids == (POLICY, CODE, DOCS)
    assert (plan.added, plan.dropped) == ((), (OTHER,))
    assert (plan.used, plan.usable) == (60, 1000)
    assert plan.rationale == "policies first, then the named code"
    call = result.call
    assert call is not None
    assert (call.model_alias, call.provider, call.model_id) == (
        "context_planner", "scripted-llm", "planner-v1")
    assert call.duration_ms == 250
    assert call.prompt_characters == len(llm.requests[0].prompt)
    assert call.response_characters == len(plan_json([POLICY, CODE, DOCS]))
    assert [r.model for r in llm.requests] == ["planner-v1"]  # model id, never the alias


def test_budget_result_and_classifications_are_never_modified() -> None:
    before = budget()
    result = escalate(before, ScriptedLLMProvider(plan_json([POLICY, CODE])))
    assert result.budget is before
    assert result.budget == budget().model_copy(update={"request": before.request})
    assert "classification" not in ContextPlan.model_fields


def test_required_first_normalisation_keeps_planner_order_and_is_deterministic() -> None:
    answer = plan_json([DOCS, CODE, OTHER, POLICY])
    first, _ = run(answer)
    second, _ = run(answer)
    assert first.plan is not None and second.plan is not None
    assert first.plan.selected_candidate_ids == (CODE, POLICY, DOCS, OTHER)
    assert first.plan == second.plan


def test_planner_may_swap_items_within_the_same_limits() -> None:
    # usable 50: REQUIRED 40, then only one 10-character item fits (budget chose b.py)
    result = escalate(budget(50, **{"source__src__b.py": 10, "doc__docs__x.md": 10}),
                      ScriptedLLMProvider(plan_json([POLICY, CODE, DOCS])))
    assert result.budget.not_selected[0].candidate.id == DOCS
    assert result.plan is not None
    assert (result.plan.added, result.plan.dropped, result.plan.used) == ((DOCS,), (OTHER,), 50)


def test_planner_constraints_and_suggestions_are_recorded_never_executed() -> None:
    result, _ = run(plan_json([POLICY, CODE], unresolved=["ADR-3 and the README disagree"],
                              suggestions=["truncate docs/x.md to its summary"]))
    plan = result.plan
    assert plan is not None
    assert [(c.kind, c.detail) for c in plan.unresolved_constraints] == [
        (ConstraintKind.PLANNER_REPORTED, "ADR-3 and the README disagree")]
    assert plan.suggestions == ("truncate docs/x.md to its summary",)
    assert plan.used == 40  # whole items only: nothing was truncated


def test_fenced_json_is_accepted() -> None:
    result, _ = run("```json\n" + plan_json([POLICY, CODE]) + "\n```")
    assert result.status is PlanStatus.PLANNED


# --- rejected plans ----------------------------------------------------------------------------


def rejected(answer: str, **kwargs: int) -> str:
    result, _ = run(answer, **kwargs)
    assert result.status is PlanStatus.FAILED
    assert result.failure_kind is PlanningFailure.INVALID_OUTPUT
    assert (result.plan, result.llm_calls) == (None, 1)
    assert result.call is not None and result.call.response_characters == len(answer)
    assert result.failure is not None
    return result.failure


def test_omitted_required_is_rejected_not_silently_readded() -> None:
    assert f"REQUIRED '{CODE}' was omitted" in rejected(plan_json([POLICY, DOCS]))


def test_selected_excluded_is_rejected() -> None:
    assert f"'{LOCK}' is not selectable: EXCLUDED" in rejected(plan_json([POLICY, CODE, LOCK]))


def test_unknown_candidate_id_is_rejected() -> None:
    assert "unknown candidate id 'source/src/invented.py'" in rejected(
        plan_json([POLICY, CODE, "source/src/invented.py"]))


def test_duplicate_selection_is_rejected() -> None:
    assert f"'{DOCS}' is selected more than once" in rejected(plan_json([POLICY, CODE, DOCS, DOCS]))


def test_plan_exceeding_the_budget_is_rejected() -> None:
    failure = rejected(plan_json([POLICY, CODE, OTHER, DOCS]), total=50)
    assert f"'{DOCS}' (20 characters) does not fit the usable budget" in failure


@pytest.mark.parametrize(("answer", "problem"), [
    ("Here is my plan: select everything", "not a JSON object"),
    ('["policy/secrets"]', "JSON list, not an object"),
    ("Sure! " + plan_json([POLICY, CODE]), "not a JSON object"),
    (json.dumps({"selected_candidate_ids": [POLICY, CODE], "rationale": "r"}),
     "unresolved_constraints: Field required"),
    (plan_json([POLICY, CODE], classification={CODE: "OPTIONAL"}),
     "classification: Extra inputs are not permitted"),
    (plan_json([POLICY, CODE], rationale=""), "rationale: String should have at least 1"),
    (json.dumps({"selected_candidate_ids": POLICY, "rationale": "r",
                 "unresolved_constraints": [], "suggestions": []}),
     "selected_candidate_ids: Input should be a valid list"),
    (json.dumps({"selected_candidate_ids": [1], "rationale": "r",
                 "unresolved_constraints": [], "suggestions": []}),
     "selected_candidate_ids.0: Input should be a valid string"),
])
def test_malformed_or_out_of_schema_output_is_rejected(answer: str, problem: str) -> None:
    assert problem in rejected(answer)


# --- unavailable / unmeasured / overflow ------------------------------------------------------


def with_missing_required() -> ContextBudgetResult:
    return budget_of({POLICY: "p" * 20, OTHER: "o" * 20},
                     item(CandidateKind.POLICY, "secrets", R), item(SRC, "src/b.py", H),
                     item(SRC, "src/gone.py", R), intent="plan")


def test_unavailable_required_cannot_be_selected_as_if_it_had_content() -> None:
    result = escalate(with_missing_required(),
                      ScriptedLLMProvider(plan_json([POLICY, "source/src/gone.py", OTHER])))
    assert result.failure_kind is PlanningFailure.INVALID_OUTPUT
    assert "has no loadable content and cannot be selected" in (result.failure or "")


def test_unavailable_required_stays_an_unresolved_constraint_of_a_valid_plan() -> None:
    llm = ScriptedLLMProvider(plan_json([POLICY, OTHER]))
    result = escalate(with_missing_required(), llm)
    assert result.status is PlanStatus.PLANNED
    assert [(c.kind, c.candidate_ids) for c in result.unresolved_constraints] == [
        (ConstraintKind.REQUIRED_UNAVAILABLE, ("source/src/gone.py",))]
    sent = {c["id"]: c["role"] for c in prompt_input(llm.requests[0].prompt)["candidates"]}
    assert sent["source/src/gone.py"] == "unavailable"


def test_unmeasured_candidate_cannot_be_selected() -> None:
    limited = budget_of({POLICY: "p" * 20, CODE: "c" * 20, OTHER: "o" * 20},
                        item(CandidateKind.POLICY, "secrets", R), item(SRC, "src/a.py", R),
                        item(SRC, "src/b.py", H), budget=limits(max_files=1), intent="plan")
    assert limited.not_selected[0].reason is BudgetReason.MAX_FILES_REACHED
    result = escalate(limited, ScriptedLLMProvider(plan_json([POLICY, CODE, OTHER])))
    assert f"'{OTHER}' is not selectable: not measured (max_files_reached)" in (
        result.failure or "")


def overflowing() -> ContextBudgetResult:
    return budget_of({POLICY: "p" * 60, CODE: "c" * 60, DOCS: "d" * 5},
                     item(CandidateKind.POLICY, "secrets", R), item(SRC, "src/a.py", R),
                     item(DOC, "docs/x.md", O), budget=limits(total=100))


def test_overflow_plan_keeps_every_required_and_still_reports_the_overflow() -> None:
    result = escalate(overflowing(), ScriptedLLMProvider(
        plan_json([CODE, POLICY], rationale="all REQUIRED; overflow is resolved")))
    plan = result.plan
    assert plan is not None and result.status is PlanStatus.PLANNED
    assert (plan.used, plan.usable) == (120, 100)
    assert [c.kind for c in plan.unresolved_constraints] == [ConstraintKind.REQUIRED_OVERFLOW]
    assert "by 20" in plan.unresolved_constraints[0].detail


def test_overflow_plan_cannot_add_anything_else() -> None:
    result = escalate(overflowing(), ScriptedLLMProvider(plan_json([POLICY, CODE, DOCS])))
    assert result.failure_kind is PlanningFailure.INVALID_OUTPUT
    assert f"'{DOCS}' is not selectable: not measured (required_overflow)" in (result.failure or "")


# --- provider failure: the deterministic result stands ----------------------------------------


@pytest.mark.parametrize("error", [
    ProviderCallError("scripted-llm", "timed out after 30s"),
    ProviderCallError("scripted-llm", "HTTP 503"),
    ProviderError("adapter misconfigured"),
])
def test_provider_failure_keeps_the_budget_and_is_explicit(error: ProviderError) -> None:
    before = budget()
    llm = ScriptedLLMProvider(fail=error)
    result = escalate(before, llm)
    assert result.status is PlanStatus.FAILED
    assert result.failure_kind is PlanningFailure.PROVIDER_ERROR
    assert result.failure == str(error)
    assert result.budget is before and result.plan is None
    assert result.llm_calls == 1 and len(llm.requests) == 1
    assert result.call is not None and result.call.response_characters is None
    assert any("planning failed (provider_error)" in w and "deterministic budget result stands"
               in w for w in result.warnings)
    assert result.summary()["selection_source"] == "deterministic_budget"


def test_no_planner_is_failed_without_any_call() -> None:
    result = escalate(budget())
    assert (result.status, result.failure_kind, result.llm_calls) == (
        PlanStatus.FAILED, PlanningFailure.PLANNER_UNAVAILABLE, 0)
    assert result.summary()["selected_count"] == len(result.budget.selected)


# --- result invariants ------------------------------------------------------------------------


def test_result_model_rejects_a_plan_that_breaks_invariants() -> None:
    good, _ = run(plan_json([POLICY, CODE]))
    assert good.plan is not None
    dropped_required = good.plan.model_copy(update={"selected_candidate_ids": (POLICY,)})
    with pytest.raises(ValidationError, match=f"REQUIRED '{CODE}' is missing"):
        ContextEscalationResult.model_validate({**dict(good), "plan": dropped_required})
    with_excluded = good.plan.model_copy(update={"selected_candidate_ids": (POLICY, CODE, LOCK)})
    with pytest.raises(ValidationError, match="EXCLUDED"):
        ContextEscalationResult.model_validate({**dict(good), "plan": with_excluded})


def test_result_model_rejects_a_plan_hiding_harness_constraints() -> None:
    result = escalate(overflowing(), ScriptedLLMProvider(plan_json([POLICY, CODE])))
    assert result.plan is not None
    hidden = result.plan.model_copy(update={"unresolved_constraints": ()})
    with pytest.raises(ValidationError, match="every Harness constraint"):
        ContextEscalationResult.model_validate({**dict(result), "plan": hidden})


def test_result_model_ties_status_plan_failure_and_calls() -> None:
    result = escalate(budget())  # FAILED planner_unavailable: no call was made
    planned, _ = run(plan_json([POLICY, CODE]))
    with pytest.raises(ValidationError, match="LLM is called for PLANNED"):
        ContextEscalationResult.model_validate({**dict(result), "llm_calls": 1,
                                                "call": planned.call})
    with pytest.raises(ValidationError, match="call metadata"):
        ContextEscalationResult.model_validate({**dict(planned), "call": None})
    with pytest.raises(ValidationError, match="NOT_REQUIRED"):
        ContextEscalationResult.model_validate({**dict(result), "status": PlanStatus.NOT_REQUIRED})


# --- safety -------------------------------------------------------------------------------------


def test_prompt_is_about_planning_and_states_the_invariants() -> None:
    _, llm = run(plan_json([POLICY, CODE]))
    prompt = llm.requests[0].prompt
    for text in ("You are planning context, not solving the task",
                 "REQUIRED candidates cannot be removed", "EXCLUDED candidates cannot be selected",
                 "Do not invent candidate ids", "Do not alter classifications",
                 "Respect budget constraints", "Report unresolved conflicts explicitly"):
        assert text in prompt


def test_prompt_carries_metadata_never_content() -> None:
    _, llm = run(plan_json([POLICY, CODE]))
    prompt = llm.requests[0].prompt
    assert MARKER not in prompt
    data = prompt_input(prompt)
    assert set(data) == {"request", "budget", "escalation_reasons", "candidates", "constraints",
                         "withheld_candidates"}
    assert set(data["request"]) == {"intent", "mode", "source", "instruction"}
    by_id = {c["id"]: c for c in data["candidates"]}
    assert list(by_id) == [POLICY, CODE, OTHER, DOCS, LOCK]  # ids unchanged, budget order
    assert by_id[CODE] | {} == {
        "id": CODE, "kind": "source", "title": "src/a.py", "classification": "REQUIRED",
        "selected_by": "deterministic", "evidence": "explicit_source_reference",
        "confidence": None, "category": "source_code", "size": 20, "budget_reason": "required",
        "selected_by_budget": True, "role": "mandatory", "conflicts": []}
    assert by_id[LOCK]["role"] == "not_selectable"
    assert data["escalation_reasons"] == ["architectural_task"]


def test_secret_looking_request_is_never_sent() -> None:
    llm = ScriptedLLMProvider(plan_json([POLICY, CODE]))
    unsafe = budget_of({POLICY: "p"}, item(CandidateKind.POLICY, "secrets", R), intent="plan",
                       instruction="deploy with OPENAI_API_KEY=sk-live-1234567890abcdefghijkl")
    result = escalate(unsafe, llm)
    assert llm.requests == []
    assert (result.status, result.failure_kind, result.llm_calls) == (
        PlanStatus.FAILED, PlanningFailure.UNSAFE_INPUT, 0)
    assert "openai_style_key" in (result.failure or "")
    assert "sk-live" not in (result.failure or "")  # rule names only, never the text


def withheld_budget(path: str, cls: ContextClass, *, title: str | None = None
                    ) -> ContextBudgetResult:
    unsafe = candidate(SRC, path)
    if title is not None:
        unsafe = unsafe.model_copy(update={"title": title})
    decision = ClassifiedContextCandidate(
        candidate=unsafe,
        classification=ContextClassification(
            classification=cls, selected_by=SelectedBy.DETERMINISTIC,
            evidence=Evidence.EXPLICIT_SOURCE_REFERENCE if cls is R
            else Evidence.NAMED_DIRECTORY_ENTRY, reason="rule"))
    return budget_of({POLICY: "p" * 5, unsafe.id: "v" * 5},
                     item(CandidateKind.POLICY, "secrets", R), decision, intent="plan")


def test_env_file_candidate_is_withheld_and_recorded() -> None:
    llm = ScriptedLLMProvider(plan_json([POLICY]))
    result = escalate(withheld_budget("config/.env", O), llm)
    prompt = llm.requests[0].prompt
    assert ".env" not in prompt
    assert prompt_input(prompt)["withheld_candidates"] == 1
    assert result.plan is not None
    withheld = [c for c in result.plan.unresolved_constraints
                if c.kind is ConstraintKind.WITHHELD]
    assert [c.candidate_ids for c in withheld] == [("source/config/.env",)]
    assert "secret_file_name" in withheld[0].detail


def test_token_like_title_is_withheld_and_cannot_be_selected() -> None:
    token = "ghp_" + "a" * 36
    llm = ScriptedLLMProvider(plan_json([POLICY, "source/src/notes.md"]))
    result = escalate(withheld_budget("src/notes.md", O, title=f"notes {token}"), llm)
    assert token not in llm.requests[0].prompt
    assert "unknown candidate id 'source/src/notes.md'" in (result.failure or "")


def test_withheld_required_is_kept_by_the_harness() -> None:
    llm = ScriptedLLMProvider(plan_json([POLICY]))
    result = escalate(withheld_budget("config/.env", R), llm)
    assert ".env" not in llm.requests[0].prompt
    assert result.plan is not None
    assert result.plan.selected_candidate_ids == (POLICY, "source/config/.env")

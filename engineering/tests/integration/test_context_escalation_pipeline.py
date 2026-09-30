"""V1.4 end to end, offline: EngineeringRequest -> discovery -> classification -> budget
-> escalation decision -> scripted LLM (LLMProvider via ModelResolver) -> ContextPlan.

A real temporary project, the real library loader, the real memory service over
the fake backend and no decision provider. The planner model is a configured
alias (`context_planner` -> provider `scripted-llm`) whose adapter is a test-only
LLMProvider that plans like a careful model would: every mandatory item, then the
smallest selectable items that fit (a different order than the budget's).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from classification_helpers import request
from escalation_helpers import ScriptedLLMProvider, plan_json, prompt_input
from library_helpers import write_artifact
from typer.testing import CliRunner

from orchestrator.cli import EXIT_REQUIRED_CONFLICT, app
from orchestrator.config import HarnessConfig, load_config
from orchestrator.context.budget.budgeter import build_budgeter
from orchestrator.context.budget.models import BudgetStatus, ContextBudgetResult
from orchestrator.context.classification.classifier import build_classifier
from orchestrator.context.classification.models import ContextClass
from orchestrator.context.discovery import build_discovery
from orchestrator.context.escalation.models import (
    ConstraintKind,
    ContextEscalationResult,
    EscalationReason,
    PlanningFailure,
    PlanStatus,
)
from orchestrator.context.escalation.planner import build_escalation, open_context_planner
from orchestrator.core.exceptions import ProviderCallError
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.loader import LIBRARY_ROOT_ENV
from orchestrator.memory.fake import FakeMemoryProvider
from orchestrator.memory.service import MemoryService
from orchestrator.providers.registry import ProviderRegistry

WriteConfig = Callable[[str, str], Path]
runner = CliRunner()

REQUEST = ("fix rounding in src/billing/invoice.py for the whole src/billing/ package; "
           "see docs/adr/0001-cents.md")
SIMPLE = "fix rounding in src/billing/invoice.py"
REQUIRED_IDS = {"policy/secrets", "policy/security", "instructions/AGENTS.md",
                "source/src/billing/invoice.py"}
EXCLUDED_IDS = {"adr/docs/adr/0001-cents.md", "source/src/billing/uv.lock"}


def sized(path: Path, head: str, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + "x" * (size - len(head)), encoding="utf-8")


@pytest.fixture
def project(harness_root: Path, library_root: Path, write_config: WriteConfig) -> Path:
    root = harness_root.parent
    sized(root / "AGENTS.md", "# Agents\n", 200)
    sized(root / "docs" / "overview.md", "# Overview\n", 300)
    sized(root / "docs" / "adr" / "0001-cents.md",
          "# ADR-0001: Cents\n- Status: Superseded by ADR-0002\n", 120)
    sized(root / "src" / "billing" / "invoice.py", "# invoice\n", 300)
    sized(root / "src" / "billing" / "rates.py", "# rates\n", 150)
    sized(root / "src" / "billing" / "tax.py", "# tax\n", 400)
    sized(root / "src" / "billing" / "uv.lock", "# lock\n", 50)
    write_artifact(library_root, "secrets", "policy", body="S" * 100)
    write_artifact(library_root, "security", "policy", body="Y" * 100)
    write_artifact(library_root, "testing", "guideline", body="G" * 100)
    write_config("memory.yaml", """
        version: 1
        memory:
          enabled: true
          backend: mem0
          mem0: {base_url: "http://localhost:1"}
    """)
    write_config("providers.yaml", """
        version: 1
        providers:
          jev: {kind: jev, enabled: false}
          scripted-llm: {kind: scripted, enabled: true}
    """)
    write_config("models.yaml", """
        version: 1
        models:
          decision: {provider: jev, model_id: jev-latest}
          context_planner: {provider: scripted-llm, model_id: planner-v1}
    """)
    return root


def configure(write_config: WriteConfig, budget: str, model: str = "context_planner") -> None:
    write_config("context.yaml", f"""
        version: 1
        context:
          enabled: true
          discovery:
            instruction_files: [AGENTS.md]
            documentation_paths: [docs]
            adr_paths: [docs/adr]
            source_roots: [src]
            exclude_dirs: [harness, library]
          budget: {budget}
          escalation: {{model: {model}}}
    """)


def careful_planner(prompt: str) -> str:
    """Every mandatory item, then the smallest selectable items that still fit."""
    data = prompt_input(prompt)
    budget = data["budget"]
    mandatory = [c for c in data["candidates"] if c["role"] == "mandatory"]
    used = sum(c["size"] for c in mandatory)
    chosen = [c["id"] for c in mandatory]
    for c in sorted((c for c in data["candidates"] if c["role"] == "selectable"),
                    key=lambda c: (c["size"], c["id"])):
        if used + c["size"] <= budget["usable"]:
            chosen.append(c["id"])
            used += c["size"]
    return plan_json(chosen, rationale="mandatory first, then the smallest items that fit",
                     unresolved=["overflow"] if budget["overflow"] else [])


def budget_for(harness_root: Path, library_root: Path, text: str,
               intent: str | None = None) -> tuple[HarnessConfig, ContextBudgetResult]:
    config = load_config(harness_root)
    library = GlobalLibrary.load(library_root)
    memory = MemoryService(FakeMemoryProvider(), project=config.project.name)
    memory.add("Invoice rounding is half-even", scope=memory.scope("project"),
               source=memory.source("decision:D-1"))
    subject = request(text).model_copy(update={"intent": intent}) if intent else request(text)
    discovered = build_discovery(config, library, memory=memory).discover(subject)
    classified = build_classifier(config).classify(discovered)
    return config, build_budgeter(config, library).budget(classified)


def pipeline(harness_root: Path, library_root: Path, llm: ScriptedLLMProvider, text: str = REQUEST,
             intent: str | None = "plan") -> ContextEscalationResult:
    config, budget = budget_for(harness_root, library_root, text, intent)
    registry = ProviderRegistry()
    registry.register_llm(llm)
    planner = open_context_planner(config, registry)
    return build_escalation(config, planner=planner).escalate(budget)


def classes(result: ContextEscalationResult) -> dict[str, ContextClass]:
    return {i.candidate.id: i.classified.classification.classification
            for i in result.budget.items}


def test_architectural_request_is_planned_within_every_invariant(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 1160, reserve: 200}")  # usable 960
    llm = ScriptedLLMProvider(careful_planner)
    result = pipeline(harness_root, library_root, llm)

    # every class is present in the scenario
    found = classes(result)
    assert {cid for cid, cls in found.items() if cls is ContextClass.REQUIRED} == REQUIRED_IDS
    assert {cid for cid, cls in found.items() if cls is ContextClass.EXCLUDED} == EXCLUDED_IDS
    assert {"guideline/testing", "source/src/billing/rates.py", "source/src/billing/tax.py"} <= {
        cid for cid, cls in found.items() if cls is ContextClass.HIGH_VALUE}
    assert {"doc/docs/overview.md", "memory/fake-000001"} <= {
        cid for cid, cls in found.items() if cls is ContextClass.OPTIONAL}

    assert result.escalation.reasons == (EscalationReason.ARCHITECTURAL_TASK,)
    assert result.status is PlanStatus.PLANNED and len(llm.requests) == 1
    plan = result.plan
    assert plan is not None
    selected = plan.selected_candidate_ids
    assert REQUIRED_IDS == set(selected[:4])  # REQUIRED kept, and first
    assert not EXCLUDED_IDS & set(selected)  # EXCLUDED never
    assert plan.used <= plan.usable == 960  # budget respected
    # the planner reorganised: the 29-character memory replaces the 150-character rates.py
    assert (plan.added, plan.dropped) == (("memory/fake-000001",), ("source/src/billing/rates.py",))
    assert result.budget.status is BudgetStatus.SUCCESS
    assert result.call is not None and result.call.model_alias == "context_planner"


def test_simple_task_with_small_context_never_calls_the_llm(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 100000, reserve: 20000}")
    llm = ScriptedLLMProvider(careful_planner)
    result = pipeline(harness_root, library_root, llm, text=SIMPLE, intent=None)
    assert result.budget.status is BudgetStatus.SUCCESS
    assert not result.escalation.required and result.status is PlanStatus.NOT_REQUIRED
    assert llm.requests == [] and result.llm_calls == 0 and result.plan is None
    assert result.summary()["selection_source"] == "deterministic_budget"


def test_required_overflow_is_planned_but_stays_unresolved(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 800, reserve: 200}")  # usable 600 < REQUIRED 700
    llm = ScriptedLLMProvider(careful_planner)
    result = pipeline(harness_root, library_root, llm, intent=None)
    assert result.escalation.reasons == (EscalationReason.REQUIRED_OVERFLOW,)
    assert len(llm.requests) == 1
    plan = result.plan
    assert plan is not None and set(plan.selected_candidate_ids) == REQUIRED_IDS
    assert (plan.used, plan.usable) == (700, 600)
    kinds = [c.kind for c in plan.unresolved_constraints]
    assert kinds[0] is ConstraintKind.REQUIRED_OVERFLOW
    assert ConstraintKind.PLANNER_REPORTED in kinds
    assert result.budget.status is BudgetStatus.REQUIRED_OVERFLOW


def test_provider_failure_preserves_the_deterministic_budget(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 1160, reserve: 200}")
    llm = ScriptedLLMProvider(fail=ProviderCallError("scripted-llm", "timed out after 30s"))
    result = pipeline(harness_root, library_root, llm)
    _, deterministic = budget_for(harness_root, library_root, REQUEST, "plan")
    assert result.status is PlanStatus.FAILED
    assert result.failure_kind is PlanningFailure.PROVIDER_ERROR
    assert [i.candidate.id for i in result.budget.selected] == [
        i.candidate.id for i in deterministic.selected]
    assert result.budget.usage == deterministic.usage
    assert result.summary()["selection_source"] == "deterministic_budget"


def test_plan_is_independent_of_cwd(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(write_config, "{total: 1160, reserve: 200}")
    first = pipeline(harness_root, library_root, ScriptedLLMProvider(careful_planner))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    second = pipeline(harness_root, library_root, ScriptedLLMProvider(careful_planner))
    assert first.plan == second.plan


# --- CLI (no LLM adapter exists: the planner is unavailable outside tests) ----------------------


def invoke(harness_root: Path, library_root: Path, *args: str) -> tuple[int, dict[str, Any]]:
    result = runner.invoke(app, ["--root", str(harness_root), "context", "plan", *args],
                           env={LIBRARY_ROOT_ENV: str(library_root)})
    data = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    return result.exit_code, data


def test_cli_without_trigger_exits_zero_with_zero_llm_calls(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 100000, reserve: 20000}", model="null")
    code, data = invoke(harness_root, library_root, SIMPLE)
    assert code == 0
    assert data["summary"] | {} == {
        "escalation_required": False, "reasons": [], "plan_status": "NOT_REQUIRED",
        "llm_calls": 0, "provider": None, "model": None, "budget_status": "SUCCESS",
        "selected_count": len(data["budget"]["selected"]),
        "selection_source": "deterministic_budget", "unresolved_constraints": [],
        "failure": None}
    assert all("content" not in i for i in data["budget"]["selected"])


def test_cli_escalation_without_planner_keeps_the_budget_and_exits_3(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 100000, reserve: 20000}", model="null")
    code, data = invoke(harness_root, library_root, REQUEST, "--intent", "plan", "--content")
    assert code == EXIT_REQUIRED_CONFLICT
    summary = data["summary"]
    assert (summary["escalation_required"], summary["reasons"], summary["plan_status"],
            summary["llm_calls"]) == (True, ["architectural_task"], "FAILED", 0)
    assert data["failure_kind"] == "planner_unavailable"
    assert "no planner model is configured" in summary["failure"]
    assert all(i["content"] for i in data["budget"]["selected"])  # --content

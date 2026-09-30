"""V1.3 end to end, offline: EngineeringRequest -> discovery -> classification -> budget.

A real temporary project, the real library loader, the real memory service over
the fake backend, no decision provider (unresolved candidates fall back to
OPTIONAL). Sizes are exact so usage can be asserted to the character.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from classification_helpers import request
from library_helpers import write_artifact
from typer.testing import CliRunner

from orchestrator.cli import EXIT_REQUIRED_CONFLICT, app
from orchestrator.config import HarnessConfig, load_config
from orchestrator.context.budget.budgeter import build_budgeter
from orchestrator.context.budget.models import BudgetReason, BudgetStatus, ContextBudgetResult
from orchestrator.context.classification.classifier import build_classifier
from orchestrator.context.classification.models import ContextClass, SelectedBy
from orchestrator.context.discovery import build_discovery
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.loader import LIBRARY_ROOT_ENV
from orchestrator.memory.fake import FakeMemoryProvider
from orchestrator.memory.service import MemoryService

WriteConfig = Callable[[str, str], Path]
runner = CliRunner()

REQUEST = ("fix rounding in src/billing/invoice.py for the whole src/billing/ package; "
           "see docs/adr/0001-cents.md")
MEMORY = "Invoice rounding is half-even"  # 29 characters


def sized(path: Path, head: str, size: int) -> None:
    """A file of exactly `size` characters starting with `head`."""
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
    return root


def configure(write_config: WriteConfig, budget: str) -> None:
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
    """)


def pipeline(harness_root: Path, library_root: Path) -> ContextBudgetResult:
    config: HarnessConfig = load_config(harness_root)
    library = GlobalLibrary.load(library_root)
    memory = MemoryService(FakeMemoryProvider(), project=config.project.name)
    memory.add(MEMORY, scope=memory.scope("project"), source=memory.source("decision:D-1"))
    discovered = build_discovery(config, library, memory=memory).discover(request(REQUEST))
    classified = build_classifier(config).classify(discovered)
    return build_budgeter(config, library).budget(classified)


def table(result: ContextBudgetResult) -> dict[str, tuple[str, str, int | None]]:
    return {i.candidate.id: (i.classified.classification.classification.value, i.reason.value,
                             i.size) for i in result.items}


REQUIRED_IDS = ["policy/secrets", "policy/security", "instructions/AGENTS.md",
                "source/src/billing/invoice.py"]


def test_mixed_scenario_required_all_high_value_partly_optional_out_excluded_never(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 1160, reserve: 200}")  # usable 960
    result = pipeline(harness_root, library_root)

    assert table(result) == {
        # REQUIRED policies, instruction and explicitly named source: 100+100+200+300 = 700
        "policy/secrets": ("REQUIRED", "required", 100),
        "policy/security": ("REQUIRED", "required", 100),
        "instructions/AGENTS.md": ("REQUIRED", "required", 200),
        "source/src/billing/invoice.py": ("REQUIRED", "required", 300),
        # HIGH_VALUE guideline and directory entries: 100 + 150 fit (950), 400 does not
        "guideline/testing": ("HIGH_VALUE", "within_budget", 100),
        "source/src/billing/rates.py": ("HIGH_VALUE", "within_budget", 150),
        "source/src/billing/tax.py": ("HIGH_VALUE", "total_budget_exhausted", 400),
        # OPTIONAL (fallback) documentation and memory: only 10 characters are left
        "doc/docs/overview.md": ("OPTIONAL", "total_budget_exhausted", 300),
        "memory/fake-000001": ("OPTIONAL", "total_budget_exhausted", 29),
        # EXCLUDED: never loaded
        "adr/docs/adr/0001-cents.md": ("EXCLUDED", "excluded_by_classification", None),
        "source/src/billing/uv.lock": ("EXCLUDED", "excluded_by_classification", None),
    }
    assert result.status is BudgetStatus.SUCCESS
    assert [i.candidate.id for i in result.selected] == [
        *REQUIRED_IDS, "guideline/testing", "source/src/billing/rates.py"]
    usage = result.usage
    assert (usage.total, usage.reserve, usage.usable, usage.used, usage.remaining) == (
        1160, 200, 960, 950, 10)
    assert (usage.files, usage.adrs, usage.memories) == (3, 0, 0)
    assert usage.by_category["library"] == 300 and usage.by_category["source_code"] == 450
    # both layers of "why" are kept: the classification's and the budget's
    adr = next(i for i in result.excluded if i.candidate.id.startswith("adr/"))
    assert adr.classified.classification.evidence.value == "superseded_adr"
    memory = next(i for i in result.not_selected if i.candidate.id.startswith("memory/"))
    assert memory.classified.classification.selected_by is SelectedBy.FALLBACK
    assert all(i.content is not None for i in result.selected)
    assert result.selected[3].content.startswith("# invoice\n")  # type: ignore[union-attr]


def test_required_overflow_keeps_every_required_and_considers_nothing_else(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 800, reserve: 200}")  # usable 600 < REQUIRED 700
    result = pipeline(harness_root, library_root)
    assert result.status is BudgetStatus.REQUIRED_OVERFLOW
    assert [i.candidate.id for i in result.selected] == REQUIRED_IDS
    assert (result.usage.used, result.usage.overflow, result.usage.remaining) == (700, 100, 0)
    assert {i.reason for i in result.not_selected} == {BudgetReason.REQUIRED_OVERFLOW}
    assert all(i.size is None for i in result.not_selected)  # never loaded
    assert any("exceeds the usable budget (600) by 100" in w for w in result.warnings)


def test_with_room_to_spare_everything_but_excluded_enters_in_priority_order(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{total: 100000, reserve: 20000}")
    result = pipeline(harness_root, library_root)
    assert result.status is BudgetStatus.SUCCESS
    assert [(i.classified.classification.classification, i.candidate.id)
            for i in result.selected] == [
        *((ContextClass.REQUIRED, cid) for cid in REQUIRED_IDS),
        (ContextClass.HIGH_VALUE, "guideline/testing"),
        (ContextClass.HIGH_VALUE, "source/src/billing/rates.py"),
        (ContextClass.HIGH_VALUE, "source/src/billing/tax.py"),
        (ContextClass.OPTIONAL, "doc/docs/overview.md"),
        (ContextClass.OPTIONAL, "memory/fake-000001"),
    ]
    assert result.not_selected == ()
    assert len(result.excluded) == 2
    assert result.usage.used == 700 + 100 + 150 + 400 + 300 + 29


def test_pipeline_is_deterministic_and_independent_of_cwd(
    harness_root: Path, project: Path, library_root: Path, write_config: WriteConfig,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure(write_config, "{total: 1160, reserve: 200}")
    first = pipeline(harness_root, library_root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    second = pipeline(harness_root, library_root)
    assert table(first) == table(second)
    assert first.usage == second.usage
    assert [i.content for i in first.selected] == [i.content for i in second.selected]


# --- CLI ------------------------------------------------------------------------------------------


def invoke(harness_root: Path, library_root: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    result = runner.invoke(
        app, ["--root", str(harness_root), "context", "budget", REQUEST, "--ref", "T-3", *extra],
        env={LIBRARY_ROOT_ENV: str(library_root)},
    )
    data = json.loads(result.stdout) if result.stdout.startswith("{") else {}
    return result.exit_code, data


def test_cli_budget_success_json(harness_root: Path, project: Path, library_root: Path,
                                 write_config: WriteConfig) -> None:
    write_config("memory.yaml", "version: 1\nmemory: {enabled: false}\n")
    configure(write_config, "{total: 1160, reserve: 200}")
    code, data = invoke(harness_root, library_root)
    assert code == 0
    assert data["status"] == "SUCCESS"
    usage = data["usage"]
    assert {key: usage[key] for key in ("total", "reserve", "usable", "used", "remaining")} == {
        "total": 1160, "reserve": 200, "usable": 960, "used": 950, "remaining": 10}
    assert (len(data["selected"]), len(data["not_selected"]), len(data["excluded"])) == (6, 2, 2)
    for entry in data["selected"]:
        assert "content" not in entry  # summary view by default
        assert {"classified", "category", "reason", "size", "included_size"} <= set(entry)
    tax = next(e for e in data["not_selected"]
               if e["classified"]["candidate"]["id"] == "source/src/billing/tax.py")
    assert (tax["classified"]["classification"]["classification"], tax["reason"],
            tax["size"]) == ("HIGH_VALUE", "total_budget_exhausted", 400)
    assert data["request"]["origin_ref"] == "T-3"


def test_cli_budget_content_flag_includes_selected_text(harness_root: Path, project: Path,
                                                       library_root: Path,
                                                       write_config: WriteConfig) -> None:
    write_config("memory.yaml", "version: 1\nmemory: {enabled: false}\n")
    configure(write_config, "{total: 1160, reserve: 200}")
    code, data = invoke(harness_root, library_root, "--content")
    assert code == 0
    texts = [entry["content"] for entry in data["selected"]]
    assert texts[0] == "S" * 100
    assert ContextBudgetResult.model_validate(data).status is BudgetStatus.SUCCESS


def test_cli_budget_required_overflow_exits_3(harness_root: Path, project: Path,
                                              library_root: Path,
                                              write_config: WriteConfig) -> None:
    write_config("memory.yaml", "version: 1\nmemory: {enabled: false}\n")
    configure(write_config, "{total: 800, reserve: 200}")
    code, data = invoke(harness_root, library_root)
    assert code == EXIT_REQUIRED_CONFLICT == 3
    assert data["status"] == "REQUIRED_OVERFLOW"


def test_cli_budget_invalid_config_exits_1(harness_root: Path, project: Path, library_root: Path,
                                           write_config: WriteConfig) -> None:
    configure(write_config, "{total: 100, reserve: 100}")
    result = runner.invoke(app, ["--root", str(harness_root), "context", "budget", "x"],
                           env={LIBRARY_ROOT_ENV: str(library_root)})
    assert result.exit_code == 1
    assert "reserve" in result.stderr

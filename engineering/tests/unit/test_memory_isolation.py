"""Architectural guards for V0.3 memory: decoupling, no automatic ingestion, no Mem0 leakage."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "orchestrator"


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _modules_importing(prefix: str) -> set[str]:
    return {
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if any(name.startswith(prefix) for name in _imports(path))
    }


def test_core_does_not_depend_on_memory() -> None:
    assert not {m for m in _modules_importing("orchestrator.memory") if m.startswith("core/")}


def test_memory_does_not_know_cli_requests_or_inference_providers() -> None:
    forbidden = ("orchestrator.cli", "orchestrator.intake", "orchestrator.core.request",
                 "orchestrator.core.admission", "orchestrator.doctor", "orchestrator.providers",
                 "typer")
    for path in (PACKAGE / "memory").rglob("*.py"):
        leaked = {n for n in _imports(path) if n.startswith(forbidden)}
        assert not leaked, f"{path} imports {leaked}"


def test_only_the_composition_step_knows_the_mem0_adapter() -> None:
    assert _modules_importing("orchestrator.memory.mem0") == {"memory/service.py"}


def test_no_automatic_ingestion_only_explicit_consumers_open_memory() -> None:
    # V0.3: memory is written only by explicit operator commands; the doctor only reads health.
    assert _modules_importing("orchestrator.memory.service") == {"cli.py", "doctor.py"}


def test_fake_is_never_wired_into_production_code() -> None:
    assert _modules_importing("orchestrator.memory.fake") == set()

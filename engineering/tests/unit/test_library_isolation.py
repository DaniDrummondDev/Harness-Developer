"""Architectural guards for the V1 Global Library: no coupling to CLI, providers,
memory, decisions or network; no code execution primitives in the loader."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "orchestrator"
LIBRARY = PACKAGE / "library"


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_library_does_not_know_cli_providers_memory_decisions_or_network() -> None:
    forbidden = ("orchestrator.cli", "orchestrator.doctor", "orchestrator.providers",
                 "orchestrator.memory", "orchestrator.decisions", "orchestrator.intake",
                 "typer", "rich", "urllib", "http", "socket", "subprocess",
                 "orchestrator.utils.shell")
    for path in LIBRARY.rglob("*.py"):
        leaked = {n for n in _imports(path) if n.startswith(forbidden)}
        assert not leaked, f"{path} imports {leaked}"


def test_library_uses_no_execution_primitives() -> None:
    for path in LIBRARY.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert not calls & {"eval", "exec", "compile", "__import__"}, path


def test_core_does_not_depend_on_library() -> None:
    for path in (PACKAGE / "core").rglob("*.py"):
        assert not {n for n in _imports(path) if n.startswith("orchestrator.library")}, path


def test_only_cli_and_doctor_consume_the_library() -> None:
    consumers = {
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if not path.is_relative_to(LIBRARY)
        and any(n.startswith("orchestrator.library") for n in _imports(path))
    }
    assert consumers == {"cli.py", "doctor.py"}

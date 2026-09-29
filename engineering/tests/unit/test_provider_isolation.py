"""Architectural guards for V0.2: no vendor SDKs, no network, no secrets, one-way deps."""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from orchestrator.config import ModelEntry, ProviderEntry
from orchestrator.providers.base import DecisionRequest, LLMRequest
from orchestrator.providers.fake import FakeDecisionProvider, FakeLLMProvider
from orchestrator.providers.registry import ProviderRegistry
from orchestrator.providers.resolution import ModelResolver

PACKAGE = Path(__file__).resolve().parents[2] / "orchestrator"
VENDOR_MODULES = {"openai", "anthropic", "nvidia", "typesafe", "jev", "mem0", "httpx", "requests"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_vendor_sdk_is_imported_anywhere() -> None:
    for path in PACKAGE.rglob("*.py"):
        roots = {name.split(".")[0] for name in _imports(path)}
        assert not roots & VENDOR_MODULES, f"{path} imports {roots & VENDOR_MODULES}"


def test_core_does_not_depend_on_providers() -> None:
    for path in (PACKAGE / "core").rglob("*.py"):
        assert not any(n.startswith("orchestrator.providers") for n in _imports(path)), path


def test_providers_do_not_know_cli_intake_or_requests() -> None:
    forbidden = ("orchestrator.cli", "orchestrator.intake", "orchestrator.core.request",
                 "orchestrator.core.admission", "orchestrator.doctor", "typer", "yaml")
    for path in (PACKAGE / "providers").rglob("*.py"):
        leaked = {n for n in _imports(path) if n.startswith(forbidden)}
        assert not leaked, f"{path} imports {leaked}"


def test_full_flow_runs_offline_without_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "JEV_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    registry = ProviderRegistry()
    registry.register_llm(FakeLLMProvider("gen"))
    registry.register_decision(FakeDecisionProvider("dec"))
    resolver = ModelResolver(
        models={
            "writer": ModelEntry(provider="gen", model_id="g-1"),
            "router": ModelEntry(provider="dec", model_id="d-1"),
        },
        providers={
            "gen": ProviderEntry(kind="fake", enabled=True),
            "dec": ProviderEntry(kind="fake", enabled=True),
        },
        registry=registry,
    )

    llm, writer = resolver.llm("writer")
    decision, router = resolver.decision("router")
    assert llm.complete(LLMRequest(model=writer.model_id, prompt="p")).provider == "gen"
    assert decision.decide(
        DecisionRequest(model=router.model_id, question="q?", options=("a", "b"))
    ).choice == "a"

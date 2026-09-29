"""Decision configuration (decisions.yaml / models.yaml / providers.yaml) and composition."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path

import pytest
from jev_emulator import JevEmulator

from orchestrator.config import DecisionThresholds, load_config
from orchestrator.core.exceptions import (
    ConfigValidationError,
    DecisionAuthenticationError,
    ModelNotFoundError,
    ProviderNotEnabledError,
    ProviderNotFoundError,
)
from orchestrator.decisions.service import open_decisions
from orchestrator.providers.jev import JevDecisionProvider

WriteConfig = Callable[[str, str], Path]
ENV = {"JEV_API_KEY": "test-key-not-a-secret"}
ORDER = "escalation_order: [deterministic, probabilistic, reasoning, human]"
PACKAGE = Path(__file__).resolve().parents[2] / "orchestrator"


def enable_jev(write_config: WriteConfig, extra: str = "") -> None:
    write_config("providers.yaml", f"""
        version: 1
        providers:
          jev: {{kind: jev, enabled: true{extra}}}
          openai: {{kind: openai, enabled: false}}
    """)


# --- shipped configuration ----------------------------------------------------------------------


def test_shipped_decision_config_is_declared_and_disabled(harness_root: Path) -> None:
    config = load_config(harness_root)
    assert config.decisions.model == "decision"
    assert config.decisions.thresholds == DecisionThresholds(minimum_confidence=0.70)
    assert (config.models["decision"].provider, config.models["decision"].model_id) == (
        "jev", "jev-latest",
    )
    jev = config.providers["jev"]
    assert (jev.enabled, jev.api_key_env, jev.base_url) == (
        False, "JEV_API_KEY", "https://api.typesafe.ai",
    )


def test_shipped_config_holds_no_secret() -> None:
    config_dir = PACKAGE.parent / "config"
    text = "".join(p.read_text(encoding="utf-8") for p in sorted(config_dir.glob("*.yaml")))
    assert "api_key:" not in text
    assert "Bearer" not in text
    assert "sk-" not in text


# --- thresholds ---------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0.0, 0.5, 0.7, 1.0])
def test_threshold_accepts_the_closed_unit_interval(
    harness_root: Path, write_config: WriteConfig, value: float
) -> None:
    write_config("decisions.yaml", f"""
        version: 1
        decisions: {{{ORDER}, model: decision, thresholds: {{minimum_confidence: {value}}}}}
    """)
    thresholds = load_config(harness_root).decisions.thresholds
    assert thresholds is not None and thresholds.minimum_confidence == value


@pytest.mark.parametrize(
    ("thresholds", "expected"),
    [
        ("{minimum_confidence: -0.01}", "greater than or equal to 0"),
        ("{minimum_confidence: 1.01}", "less than or equal to 1"),
        ("{minimum_confidence: high}", "valid number"),
        ("{}", "minimum_confidence: Field required"),
        ("{minimum_confidence: 0.7, auto_accept: 0.9}", "auto_accept: Extra inputs"),
    ],
)
def test_invalid_thresholds_fail_early(
    harness_root: Path, write_config: WriteConfig, thresholds: str, expected: str
) -> None:
    write_config("decisions.yaml", f"""
        version: 1
        decisions: {{{ORDER}, model: decision, thresholds: {thresholds}}}
    """)
    with pytest.raises(ConfigValidationError, match=expected):
        load_config(harness_root)


# --- decisions.yaml / models.yaml / providers.yaml ------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        (
            "decisions.yaml",
            f"decisions: {{{ORDER}, model: decision}}",
            "decisions.thresholds is missing",
        ),
        (
            "decisions.yaml",
            f"decisions: {{{ORDER}, model: nope, thresholds: {{minimum_confidence: 0.7}}}}",
            "decisions.model 'nope' is not declared in models.yaml",
        ),
        (
            "decisions.yaml",
            f"decisions: {{{ORDER}, model: Bad-Alias, thresholds: {{minimum_confidence: 0.7}}}}",
            "decisions.model",
        ),
        ("decisions.yaml", f"decisions: {{{ORDER}, provider: jev}}", "provider: Extra inputs"),
        ("decisions.yaml", "decisions: {model: decision}", "escalation_order: Field required"),
        (
            "models.yaml",
            "models: {decision: {provider: typesafe, model_id: jev-latest}}",
            "provider 'typesafe' is not declared",
        ),
        ("models.yaml", "models: {decision: {provider: jev}}", "model_id"),
        ("providers.yaml", "providers: {jev: {kind: jev, api_key: sk-1}}", "api_key: Extra"),
        ("providers.yaml", "providers: {jev: {kind: jev, api_key_env: lower}}", "api_key_env"),
        ("providers.yaml", "providers: {jev: {kind: jev, base_url: 'ftp://x'}}", "base_url"),
        ("providers.yaml", "providers: {jev: {kind: jev, timeout_seconds: 0}}", "timeout"),
    ],
)
def test_invalid_decision_configuration_fails_early(
    harness_root: Path, write_config: WriteConfig, filename: str, content: str, expected: str
) -> None:
    write_config(filename, f"version: 1\n{content}\n")
    with pytest.raises(ConfigValidationError, match=expected):
        load_config(harness_root)


# --- composition: open_decisions ---------------------------------------------------------------


def test_open_decisions_builds_the_jev_adapter_from_config(
    harness_root: Path, write_config: WriteConfig
) -> None:
    enable_jev(write_config, ", timeout_seconds: 7, base_url: 'https://jev.example.test'")
    service = open_decisions(load_config(harness_root), ENV)

    assert service.provider_id == "jev"
    assert (service.model.alias, service.model.model_id) == ("decision", "jev-latest")
    assert service.thresholds.minimum_confidence == 0.70


def test_open_decisions_routes_the_model_id_to_the_adapter(
    harness_root: Path, write_config: WriteConfig
) -> None:
    enable_jev(write_config)
    emulator = JevEmulator(pick="bug")
    service = open_decisions(load_config(harness_root), ENV, transport=emulator)

    outcome = service.decide(question="Kind?", options=("bug", "feature"), subject="x")
    assert outcome.choice == "bug"
    assert emulator.last_body["model"] == "jev-latest"  # alias resolved via models.yaml


def test_shipped_config_fails_closed_without_network(harness_root: Path) -> None:
    emulator = JevEmulator()
    with pytest.raises(ProviderNotEnabledError, match="'jev', which is disabled"):
        open_decisions(load_config(harness_root), ENV, transport=emulator)
    assert emulator.calls == []


def test_unconfigured_decisions_fail_explicitly(
    harness_root: Path, write_config: WriteConfig
) -> None:
    write_config("decisions.yaml", f"version: 1\ndecisions: {{{ORDER}}}\n")
    with pytest.raises(ProviderNotEnabledError, match="decisions are not configured"):
        open_decisions(load_config(harness_root), ENV)


def test_missing_api_key_fails_without_leaking(
    harness_root: Path, write_config: WriteConfig
) -> None:
    enable_jev(write_config)
    with pytest.raises(DecisionAuthenticationError, match=r"\$JEV_API_KEY is not set"):
        open_decisions(load_config(harness_root), {})


def test_custom_api_key_env_is_honoured(harness_root: Path, write_config: WriteConfig) -> None:
    enable_jev(write_config, ", api_key_env: HARNESS_JEV_KEY")
    config = load_config(harness_root)
    with pytest.raises(DecisionAuthenticationError, match=r"\$HARNESS_JEV_KEY"):
        open_decisions(config, ENV)
    assert open_decisions(config, {"HARNESS_JEV_KEY": "k"}).provider_id == "jev"


def test_provider_kind_without_decision_adapter_fails(
    harness_root: Path, write_config: WriteConfig
) -> None:
    write_config("providers.yaml", """
        version: 1
        providers:
          jev: {kind: jev}
          openai: {kind: openai, enabled: true}
    """)
    write_config("models.yaml", """
        version: 1
        models: {decision: {provider: openai, model_id: some-model}}
    """)
    with pytest.raises(ProviderNotFoundError, match="kind 'openai', which has no decision adapter"):
        open_decisions(load_config(harness_root), ENV)


def test_unknown_alias_is_a_model_error(harness_root: Path) -> None:
    config = load_config(harness_root)
    broken = config.model_copy(
        update={"decisions": config.decisions.model_copy(update={"model": "ghost"})}
    )
    with pytest.raises(ModelNotFoundError, match="'ghost'"):
        open_decisions(broken, ENV)


def test_jev_adapter_type_is_confined_to_composition() -> None:
    """The core never names Jev: only providers/jev.py and the composition step do."""
    importers = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any(n.startswith("orchestrator.providers.jev") or n == "orchestrator.providers.jev"
                   for n in names):
                importers.append(path.relative_to(PACKAGE).as_posix())
    assert sorted(set(importers)) == ["decisions/service.py"]
    assert JevDecisionProvider.__module__ == "orchestrator.providers.jev"


def test_decision_layer_never_imports_an_llm() -> None:
    source = "".join(p.read_text(encoding="utf-8") for p in (PACKAGE / "decisions").glob("*.py"))
    assert "LLMProvider" not in source
    assert ".complete(" not in source
    core = "".join(p.read_text(encoding="utf-8") for p in (PACKAGE / "core").glob("*.py"))
    assert "orchestrator.decisions" not in core and "orchestrator.providers" not in core

"""V1.4 escalation configuration, planner composition and the `escalation` doctor check."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from escalation_helpers import PLANNER_MODEL, ScriptedLLMProvider

from orchestrator.config import EscalationTriggers, HarnessConfig, load_config
from orchestrator.context.escalation import planner as planner_module
from orchestrator.context.escalation.planner import open_context_planner
from orchestrator.core.exceptions import (
    ConfigValidationError,
    ProviderNotEnabledError,
    ProviderNotFoundError,
)
from orchestrator.core.request import Intent
from orchestrator.doctor import CheckStatus, check_escalation
from orchestrator.providers.registry import ProviderRegistry

WriteConfig = Callable[[str, str], Path]

CONTEXT = """
    version: 1
    context:
      enabled: true
      escalation:
        {escalation}
"""


def configure(write_config: WriteConfig, escalation: str, *, planner_provider: str = "openai",
              enabled: bool = False) -> None:
    write_config("context.yaml", CONTEXT.format(escalation=escalation))
    write_config("providers.yaml", f"""
        version: 1
        providers:
          openai: {{kind: openai, enabled: {str(enabled).lower()}}}
          jev: {{kind: jev, enabled: false}}
          scripted-llm: {{kind: scripted, enabled: true}}
    """)
    write_config("models.yaml", f"""
        version: 1
        models:
          decision: {{provider: jev, model_id: jev-latest}}
          context_planner: {{provider: {planner_provider}, model_id: planner-v1}}
    """)


def test_shipped_config_enables_evaluation_without_a_planner(harness_root: Path) -> None:
    escalation = load_config(harness_root).context.escalation
    assert escalation.enabled and escalation.model is None
    assert escalation.triggers == EscalationTriggers(
        architectural_intents=[Intent.PLAN], min_specialties=3, max_high_value=12,
        min_low_confidence=3)


def test_unknown_planner_alias_fails_config_load(harness_root: Path,
                                                 write_config: WriteConfig) -> None:
    configure(write_config, "{model: missing}")
    with pytest.raises(ConfigValidationError, match=r"escalation\.model 'missing' is not declared"):
        load_config(harness_root)


@pytest.mark.parametrize(("triggers", "message"), [
    ("{architectural_intents: [unclassified]}", "absence of an intent"),
    ("{architectural_intents: [plan, plan]}", "must not repeat"),
    ("{architectural_intents: [design]}", "architectural_intents.0"),
    ("{min_specialties: 1}", "min_specialties"),
    ("{max_high_value: 0}", "max_high_value"),
    ("{max_candidates: 3}", "Extra inputs"),
])
def test_invalid_triggers_fail_fast(harness_root: Path, write_config: WriteConfig, triggers: str,
                                    message: str) -> None:
    configure(write_config, f"{{triggers: {triggers}}}")
    with pytest.raises(ConfigValidationError, match=message):
        load_config(harness_root)


def test_thresholds_can_be_disabled(harness_root: Path, write_config: WriteConfig) -> None:
    configure(write_config, "{triggers: {architectural_intents: [], min_specialties: null, "
                            "max_high_value: null, min_low_confidence: null}}")
    triggers = load_config(harness_root).context.escalation.triggers
    assert (triggers.architectural_intents, triggers.min_specialties, triggers.max_high_value,
            triggers.min_low_confidence) == ([], None, None, None)


# --- composition ------------------------------------------------------------------------------


def test_no_planner_model_is_not_openable(harness_root: Path) -> None:
    with pytest.raises(ProviderNotEnabledError, match="no planner model is configured"):
        open_context_planner(load_config(harness_root))


def test_disabled_planner_provider_fails_closed(harness_root: Path,
                                                write_config: WriteConfig) -> None:
    configure(write_config, "{model: context_planner}")
    with pytest.raises(ProviderNotEnabledError, match="disabled"):
        open_context_planner(load_config(harness_root))


def test_enabled_provider_without_an_llm_adapter_fails_closed(
    harness_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{model: context_planner}", enabled=True)
    with pytest.raises(ProviderNotFoundError, match="no LLM adapter"):
        open_context_planner(load_config(harness_root))


def test_registered_adapter_is_resolved_through_the_alias(
    harness_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{model: context_planner}", planner_provider="scripted-llm")
    registry = ProviderRegistry()
    registry.register_llm(ScriptedLLMProvider())
    planner = open_context_planner(load_config(harness_root), registry)
    assert planner.model == PLANNER_MODEL


# --- doctor -------------------------------------------------------------------------------------


def check(harness_root: Path) -> tuple[CheckStatus, str]:
    config: HarnessConfig = load_config(harness_root)
    result = check_escalation(config)
    return result.status, result.detail


def test_doctor_default_passes_and_explains_the_fallback(harness_root: Path) -> None:
    status, detail = check(harness_root)
    assert status is CheckStatus.PASS
    assert "intents plan" in detail and "no planner model" in detail
    assert "deterministic budget result stands" in detail


def test_doctor_disabled(harness_root: Path, write_config: WriteConfig) -> None:
    configure(write_config, "{enabled: false}")
    assert check(harness_root) == (
        CheckStatus.PASS, "disabled: `context plan` keeps the deterministic budget result")


def test_doctor_fails_on_a_decision_provider_used_as_llm(
    harness_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{model: decision}")
    status, detail = check(harness_root)
    assert status is CheckStatus.FAIL and "decision provider, not an LLM" in detail


def test_doctor_passes_on_a_disabled_planner_provider(
    harness_root: Path, write_config: WriteConfig,
) -> None:
    configure(write_config, "{model: context_planner}")
    status, detail = check(harness_root)
    assert status is CheckStatus.PASS
    assert "planner 'context_planner' -> openai (kind openai) / planner-v1 is disabled" in detail


def test_doctor_warns_on_an_enabled_provider_without_adapter_and_never_opens_it(
    harness_root: Path, write_config: WriteConfig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_: object) -> None:
        raise AssertionError("doctor must not build an adapter")

    monkeypatch.setattr(planner_module, "build_llm_adapter", forbidden)
    monkeypatch.setattr(planner_module, "open_context_planner", forbidden)
    configure(write_config, "{model: context_planner}", enabled=True)
    status, detail = check(harness_root)
    assert status is CheckStatus.WARN and "no LLM adapter for kind 'openai'" in detail

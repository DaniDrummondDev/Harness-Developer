from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from orchestrator.config import (
    CONFIG_FILES,
    HARNESS_ROOT_ENV,
    HarnessConfig,
    RisksFile,
    default_harness_root,
    load_config,
    load_config_file,
    missing_config_files,
    resolve_harness_root,
)
from orchestrator.core.exceptions import (
    ConfigError,
    ConfigFileNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    HarnessPathError,
)
from orchestrator.core.request import ExecutionMode

WriteConfig = Callable[[str, str], Path]


# --- valid configuration ------------------------------------------------------


def test_shipped_configuration_is_valid() -> None:
    config = load_config(default_harness_root())
    assert isinstance(config, HarnessConfig)
    assert set(CONFIG_FILES) == {p.name for p in (default_harness_root() / "config").glob("*.yaml")}


def test_load_config_returns_typed_domain_object(harness_root: Path) -> None:
    config = load_config(harness_root)

    assert config.harness_root == harness_root
    assert config.project.name == "ai-engineering-harness"
    assert config.risks.levels == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert config.decisions.escalation_order[0] == "deterministic"
    assert config.modes[ExecutionMode.INTERACTIVE].enabled is True
    assert config.memory.enabled is False
    assert all(not provider.enabled for provider in config.providers.values())


def test_config_is_immutable(harness_root: Path) -> None:
    config = load_config(harness_root)
    with pytest.raises(ValueError, match="frozen"):
        config.project.name = "other"  # type: ignore[misc]


# --- path resolution ------------------------------------------------------------


def test_project_root_is_resolved_relative_to_harness_root_not_cwd(
    harness_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir("/")
    config = load_config(harness_root)
    assert config.project_root == tmp_path.resolve()


def test_project_root_subdirectory(harness_root: Path, write_config: WriteConfig) -> None:
    (harness_root / "app").mkdir()
    write_config("project.yaml", """
        version: 1
        project:
          name: demo
          root: ./app
    """)
    assert load_config(harness_root).project_root == (harness_root / "app").resolve()


def test_missing_project_root_is_invalid(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("project.yaml", """
        version: 1
        project:
          name: demo
          root: does-not-exist
    """)
    with pytest.raises(ConfigValidationError, match=re.escape("project.root 'does-not-exist'")):
        load_config(harness_root)


def test_resolve_harness_root_precedence(harness_root: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    (other / "config").mkdir(parents=True)

    assert resolve_harness_root(harness_root, {HARNESS_ROOT_ENV: str(other)}) == harness_root
    assert resolve_harness_root(None, {HARNESS_ROOT_ENV: str(other)}) == other
    assert resolve_harness_root(None, {}) == default_harness_root()


def test_resolve_harness_root_without_config_dir_fails(tmp_path: Path) -> None:
    with pytest.raises(HarnessPathError, match="has no 'config/' directory"):
        resolve_harness_root(tmp_path, {})


# --- missing / unparsable files -----------------------------------------------------


def test_missing_required_file(harness_root: Path) -> None:
    (harness_root / "config" / "risks.yaml").unlink()

    assert missing_config_files(harness_root) == ["risks.yaml"]
    with pytest.raises(ConfigFileNotFoundError, match=r"risks\.yaml"):
        load_config(harness_root)


def test_invalid_yaml(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("models.yaml", "version: 1\nmodels: [unclosed\n")
    with pytest.raises(ConfigParseError, match="invalid YAML"):
        load_config(harness_root)


def test_empty_file(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", "")
    with pytest.raises(ConfigParseError, match="empty"):
        load_config(harness_root)


def test_top_level_must_be_mapping(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", "- a\n- b\n")
    with pytest.raises(ConfigParseError, match="must be a mapping"):
        load_config(harness_root)


def test_duplicate_keys_are_rejected(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("risks.yaml", """
        version: 1
        risks:
          levels: [LOW]
          default: LOW
          default: LOW
    """)
    with pytest.raises(ConfigParseError, match="duplicate key 'default'"):
        load_config(harness_root)


# --- schema validation ------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("risks.yaml", "version: 2\nrisks: {levels: [LOW], default: LOW}\n", "version"),
        ("risks.yaml", "risks: {levels: [LOW], default: LOW}\n", "version: Field required"),
        ("risks.yaml", "version: 1\nrisks: {levels: [LOW], default: HIGH}\n", "default risk"),
        ("risks.yaml", "version: 1\nrisks: {levels: [LOW, LOW], default: LOW}\n", "unique"),
        ("risks.yaml", "version: 1\nrisks: {levels: [low], default: low}\n", "pattern"),
        ("project.yaml", "version: 1\nproject: {name: '  ', root: ..}\n", "project.name"),
        ("project.yaml", "version: 1\nproject: {name: x, root: .., colour: red}\n", "colour"),
        ("modes.yaml", "version: 1\nmodes: {semi: {enabled: true}}\n", "modes.semi"),
        ("modes.yaml", "version: 1\nmodes: {interactive: {enabled: true}}\n", "missing: .*auton"),
        ("modes.yaml", "version: 1\nmodes: {}\n", "every execution mode must be declared"),
        ("modes.yaml", "version: 1\n", "modes: Field required"),
        (
            "modes.yaml",
            "version: 1\nmodes: {interactive: {enabled: yes-please}, autonomous: {}}\n",
            "modes.interactive.enabled",
        ),
        ("memory.yaml", "version: 1\nmemory: {enabled: true}\n", "requires|no memory.backend"),
        ("memory.yaml", "version: 1\nmemory: {enabled: maybe}\n", "memory.enabled"),
        ("providers.yaml", "version: 1\nproviders: {OpenAI: {kind: openai}}\n", "OpenAI"),
        (
            "decisions.yaml",
            "version: 1\ndecisions: {escalation_order: [probabilistic, deterministic]}\n",
            "must start with 'deterministic'",
        ),
        (
            "decisions.yaml",
            "version: 1\ndecisions: {escalation_order: [deterministic, human, reasoning]}\n",
            "'human' must be the last",
        ),
        (
            "decisions.yaml",
            "version: 1\ndecisions: {escalation_order: [deterministic, deterministic]}\n",
            "must not repeat",
        ),
    ],
)
def test_invalid_values_fail_validation(
    harness_root: Path, write_config: WriteConfig, filename: str, content: str, expected: str
) -> None:
    write_config(filename, content)
    with pytest.raises(ConfigValidationError, match=expected) as excinfo:
        load_config(harness_root)
    assert excinfo.value.path == harness_root / "config" / filename


def test_modes_are_typed_and_enabled_modes_reflect_config(
    harness_root: Path, write_config: WriteConfig
) -> None:
    config = load_config(harness_root)
    assert set(config.modes) == set(ExecutionMode)
    assert config.enabled_modes == {ExecutionMode.INTERACTIVE}  # shipped default

    write_config("modes.yaml", """
        version: 1
        modes:
          interactive: {enabled: false}
          autonomous: {enabled: true}
    """)
    assert load_config(harness_root).enabled_modes == {ExecutionMode.AUTONOMOUS}


def test_load_single_file_is_typed(harness_root: Path) -> None:
    risks = load_config_file(harness_root / "config" / "risks.yaml", RisksFile)
    assert risks.risks.default == "MEDIUM"


# --- cross-file references -------------------------------------------------------------


def test_model_must_reference_declared_provider(
    harness_root: Path, write_config: WriteConfig
) -> None:
    write_config("models.yaml", """
        version: 1
        models:
          reasoning: {provider: unknown, model_id: some-model}
    """)
    with pytest.raises(ConfigValidationError, match="provider 'unknown' is not declared"):
        load_config(harness_root)


def test_role_must_reference_declared_model(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("agents.yaml", """
        version: 1
        roles:
          architect: {model: reasoning}
    """)
    with pytest.raises(ConfigValidationError, match="model 'reasoning' is not declared"):
        load_config(harness_root)


def test_valid_references(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("models.yaml", """
        version: 1
        models:
          reasoning: {provider: openai, model_id: some-model}
          decision: {provider: jev, model_id: jev-latest}
    """)
    write_config("agents.yaml", """
        version: 1
        roles:
          architect: {model: reasoning}
    """)
    config = load_config(harness_root)
    assert config.roles["architect"].model == "reasoning"
    assert config.decisions.model == "decision"


def test_all_config_errors_share_base_class() -> None:
    for error in (ConfigFileNotFoundError, ConfigParseError, ConfigValidationError):
        assert issubclass(error, ConfigError)

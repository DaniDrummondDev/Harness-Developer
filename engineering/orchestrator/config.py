"""Declarative configuration: location, parsing, validation and domain object.

Pipeline (each stage has its own error type):

    resolve_harness_root()           -> HarnessPathError
    _parse_yaml(file)                -> ConfigFileNotFoundError / ConfigParseError
    <FileModel>.model_validate(data) -> ConfigValidationError   (per-file schema)
    _check_references(files)         -> ConfigValidationError   (cross-file invariants)
    HarnessConfig                    (resolved, immutable domain object)

Rules:
- the core holds no project values: everything project-specific lives in
  `<harness_root>/config/*.yaml`;
- every file carries `version: 1` so schemas can evolve explicitly;
- unknown keys are rejected (`extra="forbid"`), so typos fail fast;
- relative paths are resolved against the harness root, never the cwd;
- no network access and no provider SDKs: sections for future capabilities
  (providers, memory, context, ...) are validated structurally only.

To add a config file: define its `*File` model, register it in
`CONFIG_FILES`, expose it on `HarnessConfig` and ship a default YAML in
`config/`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic import ValidationError as PydanticValidationError

from orchestrator.core.exceptions import (
    ConfigFileNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    HarnessPathError,
)
from orchestrator.core.request import ExecutionMode
from orchestrator.utils.files import read_text, require_directory, resolve_path

HARNESS_ROOT_ENV = "HARNESS_ROOT"
CONFIG_DIRNAME = "config"

# Keys used as identifiers (provider, model, role, pipeline names...).
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$")]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RiskLevel = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
# Provider-agnostic decision layers (vendors such as Jev are bound in providers.yaml).
DecisionLayer = Literal["deterministic", "probabilistic", "reasoning", "human"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _VersionedFile(_StrictModel):
    version: Literal[1]


# --- project.yaml -----------------------------------------------------------


class ProjectSection(_StrictModel):
    name: NonEmptyStr
    description: str = ""
    root: NonEmptyStr = Field(description="Target project root, relative to the harness root.")
    stack: list[Identifier] = Field(default_factory=list)


class ProjectFile(_VersionedFile):
    project: ProjectSection


# --- providers.yaml / models.yaml / agents.yaml -----------------------------


class ProviderEntry(_StrictModel):
    kind: Identifier
    enabled: bool = False
    description: str = ""


class ProvidersFile(_VersionedFile):
    providers: dict[Identifier, ProviderEntry] = Field(default_factory=dict)


class ModelEntry(_StrictModel):
    provider: Identifier
    model_id: NonEmptyStr
    description: str = ""


class ModelsFile(_VersionedFile):
    models: dict[Identifier, ModelEntry] = Field(default_factory=dict)


class RoleEntry(_StrictModel):
    description: str = ""
    model: Identifier | None = None


class AgentsFile(_VersionedFile):
    roles: dict[Identifier, RoleEntry] = Field(default_factory=dict)


# --- modes.yaml / context.yaml / memory.yaml / pipelines.yaml ---------------


class FeatureSection(_StrictModel):
    enabled: bool = False
    description: str = ""


class ModesFile(_VersionedFile):
    # Keys are the domain enum, so an unknown mode name fails validation. `enabled`
    # is consumed by core.admission (V0.1): requests of a disabled mode are refused.
    modes: dict[ExecutionMode, FeatureSection]

    @model_validator(mode="after")
    def _every_mode_declared(self) -> Self:
        missing = [mode.value for mode in ExecutionMode if mode not in self.modes]
        if missing:
            raise ValueError(f"every execution mode must be declared; missing: {missing}")
        return self


class ContextFile(_VersionedFile):
    context: FeatureSection


class MemorySection(FeatureSection):
    backend: Identifier | None = None

    @model_validator(mode="after")
    def _enabled_requires_backend(self) -> Self:
        if self.enabled and self.backend is None:
            raise ValueError("memory.enabled is true but no memory.backend is set")
        return self


class MemoryFile(_VersionedFile):
    memory: MemorySection


class PipelinesFile(_VersionedFile):
    pipelines: dict[Identifier, FeatureSection] = Field(default_factory=dict)


# --- decisions.yaml / risks.yaml --------------------------------------------


class DecisionsSection(_StrictModel):
    escalation_order: list[DecisionLayer] = Field(min_length=1)

    @model_validator(mode="after")
    def _deterministic_first_human_last(self) -> Self:
        order = self.escalation_order
        if len(set(order)) != len(order):
            raise ValueError("escalation_order must not repeat layers")
        # RNF-030: deterministic rules always take precedence.
        if order[0] != "deterministic":
            raise ValueError("escalation_order must start with 'deterministic'")
        # RNF-023: humans are the final authority when present.
        if "human" in order and order[-1] != "human":
            raise ValueError("'human' must be the last layer of escalation_order")
        return self


class DecisionsFile(_VersionedFile):
    decisions: DecisionsSection


class RisksSection(_StrictModel):
    levels: list[RiskLevel] = Field(min_length=1, description="Ordered lowest to highest.")
    default: RiskLevel

    @model_validator(mode="after")
    def _default_is_known_level(self) -> Self:
        if len(set(self.levels)) != len(self.levels):
            raise ValueError("risk levels must be unique")
        if self.default not in self.levels:
            raise ValueError(f"default risk '{self.default}' is not one of {self.levels}")
        return self


class RisksFile(_VersionedFile):
    risks: RisksSection


# --- registry of required files ---------------------------------------------

CONFIG_FILES: dict[str, type[_VersionedFile]] = {
    "project.yaml": ProjectFile,
    "providers.yaml": ProvidersFile,
    "models.yaml": ModelsFile,
    "agents.yaml": AgentsFile,
    "modes.yaml": ModesFile,
    "context.yaml": ContextFile,
    "memory.yaml": MemoryFile,
    "decisions.yaml": DecisionsFile,
    "risks.yaml": RisksFile,
    "pipelines.yaml": PipelinesFile,
}


class HarnessConfig(_StrictModel):
    """Validated, resolved configuration consumed by the rest of the Harness."""

    harness_root: Path
    project_root: Path
    project: ProjectSection
    providers: dict[str, ProviderEntry]
    models: dict[str, ModelEntry]
    roles: dict[str, RoleEntry]
    modes: dict[ExecutionMode, FeatureSection]
    context: FeatureSection
    memory: MemorySection
    decisions: DecisionsSection
    risks: RisksSection
    pipelines: dict[str, FeatureSection]

    @property
    def enabled_modes(self) -> frozenset[ExecutionMode]:
        """Modes whose requests the core may admit (see core.admission.admit)."""
        return frozenset(mode for mode, section in self.modes.items() if section.enabled)


# --- location ---------------------------------------------------------------


def default_harness_root() -> Path:
    """Directory containing the `orchestrator` package (the portable harness folder)."""
    return Path(__file__).resolve().parent.parent


def resolve_harness_root(
    explicit: Path | None = None, environ: Mapping[str, str] | None = None
) -> Path:
    """Locate the harness root. Precedence: explicit > $HARNESS_ROOT > package-adjacent.

    Never depends on the current working directory (except for resolving a
    relative `explicit`/env path, which is the user's own input).

    Raises:
        HarnessPathError: the chosen root has no `config/` directory.
    """
    env = os.environ if environ is None else environ
    if explicit is not None:
        root, source = explicit, "--root"
    elif env.get(HARNESS_ROOT_ENV):
        root, source = Path(env[HARNESS_ROOT_ENV]), f"${HARNESS_ROOT_ENV}"
    else:
        root, source = default_harness_root(), "package location"

    root = root.expanduser().resolve()
    config_dir = root / CONFIG_DIRNAME
    if not config_dir.is_dir():
        raise HarnessPathError(
            f"harness root {root} (from {source}) has no '{CONFIG_DIRNAME}/' directory; "
            f"pass --root or set {HARNESS_ROOT_ENV}"
        )
    return root


def missing_config_files(harness_root: Path) -> list[str]:
    """Names of required config files absent from `<harness_root>/config`."""
    config_dir = harness_root / CONFIG_DIRNAME
    return [name for name in CONFIG_FILES if not (config_dir / name).is_file()]


# --- parsing ----------------------------------------------------------------


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of silently overriding."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key '{key}'", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _parse_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigFileNotFoundError("required configuration file is missing", path=path)
    try:
        text = read_text(path)
    except HarnessPathError as exc:
        raise ConfigParseError(str(exc), path=path) from exc
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise ConfigParseError(f"invalid YAML: {exc}", path=path) from exc
    if data is None:
        raise ConfigParseError("file is empty", path=path)
    if not isinstance(data, dict):
        raise ConfigParseError(
            f"top level must be a mapping, got {type(data).__name__}", path=path
        )
    return data


def _format_pydantic_error(exc: PydanticValidationError) -> str:
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"{location}: {error['msg']}")
    return "; ".join(lines)


def load_config_file[T: _VersionedFile](path: Path, model: type[T]) -> T:
    """Parse and validate a single config file against `model`."""
    data = _parse_yaml(path)
    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        raise ConfigValidationError(_format_pydantic_error(exc), path=path) from exc


# --- cross-file validation and assembly ---------------------------------------


def _check_references(config_dir: Path, providers: ProvidersFile, models: ModelsFile,
                      agents: AgentsFile) -> None:
    for alias, model in models.models.items():
        if model.provider not in providers.providers:
            raise ConfigValidationError(
                f"models.{alias}.provider '{model.provider}' is not declared in providers.yaml",
                path=config_dir / "models.yaml",
            )
    for role_name, role in agents.roles.items():
        if role.model is not None and role.model not in models.models:
            raise ConfigValidationError(
                f"roles.{role_name}.model '{role.model}' is not declared in models.yaml",
                path=config_dir / "agents.yaml",
            )


def load_config(harness_root: Path) -> HarnessConfig:
    """Load, validate and resolve every required file under `<harness_root>/config`.

    Raises:
        HarnessPathError: `harness_root/config` is not a directory.
        ConfigFileNotFoundError / ConfigParseError / ConfigValidationError.
    """
    config_dir = require_directory(harness_root / CONFIG_DIRNAME)

    project = load_config_file(config_dir / "project.yaml", ProjectFile)
    providers = load_config_file(config_dir / "providers.yaml", ProvidersFile)
    models = load_config_file(config_dir / "models.yaml", ModelsFile)
    agents = load_config_file(config_dir / "agents.yaml", AgentsFile)
    modes = load_config_file(config_dir / "modes.yaml", ModesFile)
    context = load_config_file(config_dir / "context.yaml", ContextFile)
    memory = load_config_file(config_dir / "memory.yaml", MemoryFile)
    decisions = load_config_file(config_dir / "decisions.yaml", DecisionsFile)
    risks = load_config_file(config_dir / "risks.yaml", RisksFile)
    pipelines = load_config_file(config_dir / "pipelines.yaml", PipelinesFile)

    _check_references(config_dir, providers, models, agents)

    project_root = resolve_path(harness_root, project.project.root)
    if not project_root.is_dir():
        raise ConfigValidationError(
            f"project.root '{project.project.root}' resolves to {project_root}, "
            "which is not an existing directory",
            path=config_dir / "project.yaml",
        )

    return HarnessConfig(
        harness_root=harness_root,
        project_root=project_root,
        project=project.project,
        providers=providers.providers,
        models=models.models,
        roles=agents.roles,
        modes=modes.modes,
        context=context.context,
        memory=memory.memory,
        decisions=decisions.decisions,
        risks=risks.risks,
        pipelines=pipelines.pipelines,
    )

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
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic import ValidationError as PydanticValidationError

from orchestrator.core.exceptions import (
    ConfigFileNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    HarnessPathError,
)
from orchestrator.core.request import ExecutionMode
from orchestrator.utils.files import read_text, require_directory, resolve_path
from orchestrator.utils.yaml_loader import load_yaml

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
    # Project profile (V1): matched deterministically against the Global Library's
    # `applies_to` (orchestrator/library). `stack` = technologies in use;
    # `capabilities` = what the project does/has (api, database, containers, ...).
    stack: list[Identifier] = Field(default_factory=list)
    capabilities: list[Identifier] = Field(default_factory=list)


class ProjectFile(_VersionedFile):
    project: ProjectSection


# --- providers.yaml / models.yaml / agents.yaml -----------------------------


EnvVarName = Annotated[str, StringConstraints(pattern=r"^[A-Z_][A-Z0-9_]*$")]
HttpBaseUrl = Annotated[str, StringConstraints(pattern=r"^https?://[^\s/]+(/[^\s]*)?$")]
Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class ProviderEntry(_StrictModel):
    """A provider id. Connection fields are optional and vendor-neutral (V0.4); an
    adapter falls back to its documented defaults when they are absent. The API key
    is never stored here: `api_key_env` names the environment variable holding it."""

    kind: Identifier
    enabled: bool = False
    description: str = ""
    base_url: HttpBaseUrl | None = None
    api_key_env: EnvVarName | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=120)


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


def _check_relative_path(value: str) -> str:
    """A path relative to the project root that cannot leave it syntactically:
    POSIX separators, not absolute, no `..`, no `~`. (Symlinks are checked at
    runtime by the discovery layer, which resolves every root.)"""
    if "\\" in value or value.startswith(("/", "~")) or ":" in value:
        raise ValueError(f"'{value}' must be a relative POSIX path inside the project")
    parts = [p for p in value.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise ValueError(f"'{value}' must not contain '..'")
    return "/".join(parts) or "."


ProjectRelativePath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    AfterValidator(_check_relative_path),
]
# A directory *name* pruned anywhere in a walk (e.g. `graft`), never a path.
DirName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.][A-Za-z0-9_.-]*$")]


class DiscoverySection(_StrictModel):
    """Context Candidate Discovery (V1.1). Every path is relative to the project
    root. Limits protect the discovery walk itself; they are not a context budget."""

    instruction_files: list[ProjectRelativePath] = Field(default_factory=list)
    documentation_paths: list[ProjectRelativePath] = Field(default_factory=list)
    adr_paths: list[ProjectRelativePath] = Field(default_factory=list)
    source_roots: list[ProjectRelativePath] = Field(default_factory=lambda: ["."])
    exclude_dirs: list[DirName] = Field(default_factory=list)
    max_files: int = Field(default=5000, ge=1, le=100_000)
    max_file_bytes: int = Field(default=1_048_576, ge=1, le=64 * 1_048_576)
    memory_results: int = Field(default=5, ge=1, le=50)


class ClassificationSection(_StrictModel):
    """Context Classification (V1.2). Deterministic rules always run first and are
    never overridden. `probabilistic` lets candidates no rule resolves go to the
    decision layer (decisions.yaml `model`, e.g. Jev), whose own
    `thresholds.minimum_confidence` is the acceptance threshold (not duplicated
    here). `max_decisions` caps decision calls per classification run; the rest
    use the conservative fallback."""

    probabilistic: bool = True
    max_decisions: int = Field(default=50, ge=1, le=500)


class ContextSection(FeatureSection):
    # `enabled` gates Context Engineering (consumed by context.discovery since V1.1).
    discovery: DiscoverySection = Field(default_factory=DiscoverySection)
    classification: ClassificationSection = Field(default_factory=ClassificationSection)


class ContextFile(_VersionedFile):
    context: ContextSection


class Mem0Section(_StrictModel):
    """Connection to a self-hosted Mem0 REST server (V0.3). The API key is never
    stored here: `api_key_env` names the environment variable that holds it."""

    base_url: HttpBaseUrl
    api_key_env: EnvVarName = "MEM0_API_KEY"
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)


class MemorySection(FeatureSection):
    # Consumed by orchestrator.memory.service.open_memory (V0.3). Only "mem0" exists.
    backend: Literal["mem0"] | None = None
    mem0: Mem0Section | None = None

    @model_validator(mode="after")
    def _enabled_requires_backend(self) -> Self:
        if self.enabled and self.backend is None:
            raise ValueError("memory.enabled is true but no memory.backend is set")
        if self.backend == "mem0" and self.mem0 is None:
            raise ValueError("memory.backend is 'mem0' but the memory.mem0 section is missing")
        return self


class MemoryFile(_VersionedFile):
    memory: MemorySection


class PipelinesFile(_VersionedFile):
    pipelines: dict[Identifier, FeatureSection] = Field(default_factory=dict)


# --- decisions.yaml / risks.yaml --------------------------------------------


class DecisionThresholds(_StrictModel):
    """Confidence thresholds (V0.4). Declarative only: the decision service uses
    `minimum_confidence` to *signal* that a fallback is required; choosing and
    running the fallback (auto accept / LLM review / human) is V5.2."""

    minimum_confidence: Probability


class DecisionsSection(_StrictModel):
    escalation_order: list[DecisionLayer] = Field(min_length=1)
    # Logical alias in models.yaml used by the probabilistic layer (V0.4).
    # None = the decision foundation is not configured (no decision can be made).
    model: Identifier | None = None
    thresholds: DecisionThresholds | None = None

    @model_validator(mode="after")
    def _deterministic_first_human_last(self) -> Self:
        if self.model is not None and self.thresholds is None:
            raise ValueError("decisions.model is set but decisions.thresholds is missing")
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
    context: ContextSection
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


def _parse_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigFileNotFoundError("required configuration file is missing", path=path)
    try:
        text = read_text(path)
    except HarnessPathError as exc:
        raise ConfigParseError(str(exc), path=path) from exc
    try:
        data = load_yaml(text)
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
                      agents: AgentsFile, decisions: DecisionsFile) -> None:
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
    decision_model = decisions.decisions.model
    if decision_model is not None and decision_model not in models.models:
        raise ConfigValidationError(
            f"decisions.model '{decision_model}' is not declared in models.yaml",
            path=config_dir / "decisions.yaml",
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

    _check_references(config_dir, providers, models, agents, decisions)

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

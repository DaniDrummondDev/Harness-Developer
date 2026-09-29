"""Harness error model.

Every error raised deliberately by the Harness derives from `HarnessError`,
so the CLI can tell expected failures (clear message, non-zero exit) apart
from bugs (traceback).

    HarnessError
    ├── ConfigError
    │   ├── ConfigFileNotFoundError   required config file is missing
    │   ├── ConfigParseError          file is not valid YAML / not a mapping
    │   └── ConfigValidationError     schema, value, cross-reference or path error
    ├── HarnessPathError              filesystem path missing or of the wrong kind
    ├── CommandError
    │   ├── CommandNotFoundError      executable does not exist / is not executable
    │   ├── CommandTimeoutError       command exceeded its timeout
    │   └── CommandFailedError        command exited non-zero (only when check=True)
    ├── RequestError
    │   ├── InvalidRequestError       raw input cannot be normalized into an EngineeringRequest
    │   └── ModeNotEnabledError       the request's mode is disabled in modes.yaml
    └── ProviderError
        ├── ProviderRegistrationError adapter rejected by the registry (duplicate id, wrong type)
        ├── ProviderNotFoundError     provider id not declared / no adapter registered for it
        ├── ProviderNotEnabledError   provider declared but `enabled: false` in providers.yaml
        ├── ProviderTypeMismatchError provider registered under the other contract (LLM/decision)
        ├── ModelNotFoundError        model alias not declared in models.yaml
        └── ProviderCallError         an adapter call failed (vendor errors are translated here)

Names intentionally avoid shadowing builtins (`EnvironmentError`) and
Pydantic (`ValidationError`).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.utils.shell import CommandResult


class HarnessError(Exception):
    """Base class for all expected Harness failures."""


class ConfigError(HarnessError):
    """Base class for configuration failures."""

    def __init__(self, message: str, *, path: Path | None = None) -> None:
        self.path = path
        super().__init__(f"{path}: {message}" if path else message)


class ConfigFileNotFoundError(ConfigError):
    """A required configuration file does not exist."""


class ConfigParseError(ConfigError):
    """A configuration file could not be parsed as a YAML mapping."""


class ConfigValidationError(ConfigError):
    """A configuration file parsed but violates its schema or invariants."""


class HarnessPathError(HarnessError):
    """A filesystem path is missing, unreadable or of the wrong kind."""


class CommandError(HarnessError):
    """Base class for local command execution failures."""


class CommandNotFoundError(CommandError):
    """The executable could not be found or is not executable."""


class CommandTimeoutError(CommandError):
    """The command did not finish within its timeout."""


class CommandFailedError(CommandError):
    """The command exited with a non-zero code and the caller required success."""

    def __init__(self, result: CommandResult) -> None:
        self.result = result
        super().__init__(f"command '{result.executable}' exited with code {result.exit_code}")


class RequestError(HarnessError):
    """Base class for request intake/admission failures."""


class InvalidRequestError(RequestError):
    """Raw input violates the EngineeringRequest contract or its invariants."""


class ModeNotEnabledError(RequestError):
    """The core refused a request because its execution mode is not enabled."""


class ProviderError(HarnessError):
    """Base class for provider abstraction failures (V0.2).

    Vendor-specific exceptions (SDK, HTTP, ...) never cross the adapter
    boundary: adapters translate them into a `ProviderError` subclass.
    """


class ProviderRegistrationError(ProviderError):
    """An adapter could not be registered (duplicate id or not a provider)."""


class ProviderNotFoundError(ProviderError):
    """No provider is declared or registered under the requested id."""


class ProviderNotEnabledError(ProviderError):
    """The provider is declared in providers.yaml but disabled (fail closed)."""


class ProviderTypeMismatchError(ProviderError):
    """The provider exists but implements the other contract (LLM vs decision)."""


class ModelNotFoundError(ProviderError):
    """The logical model alias is not declared in models.yaml."""


class ProviderCallError(ProviderError):
    """An adapter call failed. Messages must not contain prompts, outputs or secrets."""

    def __init__(self, provider_id: str, message: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"provider '{provider_id}' call failed: {message}")

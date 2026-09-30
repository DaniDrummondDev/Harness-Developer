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
    ├── ProviderError
    │   ├── ProviderRegistrationError adapter rejected by the registry (duplicate id, wrong type)
    │   ├── ProviderNotFoundError     provider id not declared / no adapter registered for it
    │   ├── ProviderNotEnabledError   provider declared but `enabled: false` in providers.yaml
    │   ├── ProviderTypeMismatchError provider registered under the other contract (LLM/decision)
    │   ├── ModelNotFoundError        model alias not declared in models.yaml
    │   ├── InvalidDecisionRequestError decision input violates DecisionRequest (no call made)
    │   └── ProviderCallError        an adapter call failed (vendor errors are translated here)
    │       ├── DecisionAuthenticationError  key missing/rejected (V0.4; raised, no fallback)
    │       ├── DecisionInvalidResponseError malformed/out-of-contract answer (V0.4; fallback)
    │       └── DecisionUnavailableError     unreachable, overloaded, 5xx (V0.4; fallback)
    │           └── DecisionTimeoutError     no answer within the timeout (V0.4; fallback)
    ├── MemoryStoreError              memory backend failure / unexpected backend response (V0.3)
    │   ├── InvalidMemoryInputError   malformed scope, source, content or query (no backend call)
    │   ├── UnsafeMemoryContentError  safe ingestion policy blocked the content (nothing stored)
    │   ├── MemoryNotFoundError       no stored memory has this id (includes malformed ids)
    │   ├── MemoryConfigurationError  memory disabled/misconfigured or credentials rejected
    │   └── MemoryUnavailableError    backend unreachable, timed out or failing (5xx)
    └── LibraryError                  Global Library failure (V1); carries the offending path
        ├── LibraryStructureError     root/type directory missing, unexpected entry, path escape
        ├── ArtifactParseError        unreadable file, missing front matter, invalid YAML
        ├── ArtifactValidationError   schema/version/type/directory mismatch, duplicate id,
        │                             unknown reference
        └── ArtifactNotFoundError     no artifact of that type has this id

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


class InvalidDecisionRequestError(ProviderError):
    """Decision input (question, options, descriptions) violates the DecisionRequest
    contract; rejected before any provider is called (V0.4)."""


class ProviderCallError(ProviderError):
    """An adapter call failed. Messages must not contain prompts, outputs or secrets."""

    def __init__(self, provider_id: str, message: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"provider '{provider_id}' call failed: {message}")


class DecisionAuthenticationError(ProviderCallError):
    """Decision provider credentials are missing or were rejected (401/403).
    A configuration problem: never turned into a fallback."""


class DecisionInvalidResponseError(ProviderCallError):
    """The decision provider answered, but outside the contract (malformed body,
    choice not in options, probability out of range...)."""


class DecisionUnavailableError(ProviderCallError):
    """The decision provider is unreachable, rate limited, overloaded or failing (5xx)."""


class DecisionTimeoutError(DecisionUnavailableError):
    """The decision provider did not answer within the configured timeout."""


class MemoryStoreError(HarnessError):
    """Base class for long-term memory failures (V0.3). Named to avoid the
    `MemoryError` builtin. Backend (Mem0, HTTP) exceptions never cross the
    adapter boundary; messages never contain memory content or credentials."""


class InvalidMemoryInputError(MemoryStoreError):
    """Input violates the memory contract (scope, source, content, query)."""


class UnsafeMemoryContentError(MemoryStoreError):
    """The safe ingestion policy blocked the content; nothing was persisted."""

    def __init__(self, rules: tuple[str, ...]) -> None:
        self.rules = rules
        super().__init__(
            "content blocked by the safe ingestion policy "
            f"(matched rules: {', '.join(rules)}); nothing was stored"
        )


class MemoryNotFoundError(MemoryStoreError):
    """No stored memory has the given id."""


class MemoryConfigurationError(MemoryStoreError):
    """Memory is disabled or misconfigured, or the backend rejected the credentials."""


class MemoryUnavailableError(MemoryStoreError):
    """The memory backend is unreachable, timed out or failed internally."""


class LibraryError(HarnessError):
    """Base class for Global Library failures (V1). Library artifacts are trusted,
    versioned files, but they are still validated and a bad one fails the load."""

    def __init__(self, message: str, *, path: Path | None = None) -> None:
        self.path = path
        super().__init__(f"{path}: {message}" if path else message)


class LibraryStructureError(LibraryError):
    """The library layout is wrong: missing root or type directory, an unexpected
    entry, or a path that resolves outside the library root."""


class ArtifactParseError(LibraryError):
    """An artifact file is unreadable, too large, lacks front matter or has invalid YAML."""


class ArtifactValidationError(LibraryError):
    """An artifact parsed but violates the schema or a library invariant (type vs
    directory, duplicate id, unknown reference)."""


class ArtifactNotFoundError(LibraryError):
    """No artifact of the requested type has the requested id."""

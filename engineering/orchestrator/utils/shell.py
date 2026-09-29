"""Local command execution.

Single entry point for running external programs. Future gates and tools
must go through `run_command` instead of calling `subprocess` directly, so
execution stays uniform, testable and auditable.

Guarantees:
- never uses a shell (`shell=False`): arguments are passed as a list, so no
  shell injection or quoting surprises;
- output is always captured and returned as a structured `CommandResult`;
- a missing executable, a missing cwd or a timeout raise typed `CommandError`s;
- a non-zero exit code is returned as data unless the caller passes `check=True`.

Logging records only the executable name, argument count, exit code and
duration — never full arguments, environment or output, since those may
contain secrets.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from orchestrator.core.exceptions import (
    CommandError,
    CommandFailedError,
    CommandNotFoundError,
    CommandTimeoutError,
    HarnessPathError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Outcome of a finished command."""

    args: tuple[str, ...]
    cwd: Path | None
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def executable(self) -> str:
        return self.args[0]

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = False,
) -> CommandResult:
    """Run `args` (executable first) without a shell and capture its output.

    Args:
        args: executable followed by its arguments. Must be non-empty.
        cwd: working directory; must exist when given.
        timeout: seconds before the process is killed; None waits forever.
        env: full environment for the child; None inherits the current one.
        check: raise `CommandFailedError` when the exit code is non-zero.

    Raises:
        ValueError: `args` is empty (programming error).
        HarnessPathError: `cwd` does not exist or is not a directory.
        CommandNotFoundError: executable missing or not executable.
        CommandTimeoutError: timeout exceeded.
        CommandFailedError: non-zero exit and `check=True`.
    """
    argv = tuple(str(arg) for arg in args)
    if not argv:
        raise ValueError("run_command requires at least the executable")
    if cwd is not None and not cwd.is_dir():
        raise HarnessPathError(f"working directory does not exist: {cwd}")

    logger.debug("running '%s' with %d argument(s) in %s", argv[0], len(argv) - 1, cwd)
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - no shell, argv list
            argv,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise CommandNotFoundError(f"executable not found: {argv[0]}") from exc
    except PermissionError as exc:
        raise CommandNotFoundError(f"executable is not executable: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeoutError(f"command '{argv[0]}' timed out after {timeout}s") from exc
    except OSError as exc:
        raise CommandError(f"could not start '{argv[0]}': {exc}") from exc

    result = CommandResult(
        args=argv,
        cwd=cwd,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.monotonic() - started,
    )
    logger.debug(
        "'%s' exited with %d in %.3fs", argv[0], result.exit_code, result.duration_seconds
    )
    if check and not result.ok:
        raise CommandFailedError(result)
    return result

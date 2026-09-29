from __future__ import annotations

import sys
from pathlib import Path

import pytest

from orchestrator.core.exceptions import (
    CommandFailedError,
    CommandNotFoundError,
    CommandTimeoutError,
    HarnessPathError,
)
from orchestrator.utils.shell import run_command

PY = sys.executable


def test_success_captures_stdout() -> None:
    result = run_command([PY, "-c", "print('hello')"])
    assert result.ok
    assert result.exit_code == 0
    assert result.stdout == "hello\n"
    assert result.stderr == ""
    assert result.executable == PY
    assert result.duration_seconds >= 0


def test_captures_stderr() -> None:
    result = run_command([PY, "-c", "import sys; sys.stderr.write('oops')"])
    assert result.stderr == "oops"


def test_nonzero_exit_is_returned_as_data() -> None:
    result = run_command([PY, "-c", "import sys; sys.exit(3)"])
    assert not result.ok
    assert result.exit_code == 3


def test_nonzero_exit_raises_when_checked() -> None:
    with pytest.raises(CommandFailedError) as excinfo:
        run_command([PY, "-c", "import sys; print('x'); sys.exit(2)"], check=True)
    assert excinfo.value.result.exit_code == 2
    assert excinfo.value.result.stdout == "x\n"


def test_missing_executable() -> None:
    with pytest.raises(CommandNotFoundError, match="executable not found"):
        run_command(["definitely-not-a-real-binary-xyz"])


def test_non_executable_file(tmp_path: Path) -> None:
    script = tmp_path / "script.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o644)
    with pytest.raises(CommandNotFoundError, match="not executable"):
        run_command([str(script)])


def test_timeout() -> None:
    with pytest.raises(CommandTimeoutError, match="timed out"):
        run_command([PY, "-c", "import time; time.sleep(5)"], timeout=0.2)


def test_cwd_is_used(tmp_path: Path) -> None:
    result = run_command([PY, "-c", "import os; print(os.getcwd())"], cwd=tmp_path)
    assert Path(result.stdout.strip()) == tmp_path.resolve()


def test_missing_cwd(tmp_path: Path) -> None:
    with pytest.raises(HarnessPathError, match="working directory"):
        run_command([PY, "-c", "pass"], cwd=tmp_path / "missing")


def test_no_shell_interpretation() -> None:
    # With a shell, `$HOME` and `;` would be interpreted. Here they are literal args.
    result = run_command([PY, "-c", "import sys; print(sys.argv[1])", "$HOME; echo injected"])
    assert result.stdout == "$HOME; echo injected\n"


def test_empty_args_is_programming_error() -> None:
    with pytest.raises(ValueError, match="at least the executable"):
        run_command([])

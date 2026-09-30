"""Safe, bounded, read-mostly access to project files for discovery (V1.1).

Rules (every file-based discoverer goes through `ProjectFiles`):
- everything is anchored at the resolved project root; a configured root that
  resolves outside it is fatal (`ContextDiscoveryError`), a request-supplied
  path that does so is rejected with a warning;
- walks never follow symlinked directories; a symlinked file is accepted only
  if its target is inside the project root;
- hidden entries, the built-in excluded directories (VCS, virtualenvs,
  dependencies, caches, build output) and configured `exclude_dirs` are pruned;
- files whose name looks like a secret (`.env*`, keys, keystores, credential
  files) are never candidates, even when named explicitly;
- each walk visits at most `max_files` files (then stops with a warning); files
  over `max_file_bytes` are skipped using `stat`, never read;
- content is never read, except the first `HEAD_BYTES` of Markdown files to
  extract a title/status; nothing is executed, evaluated or rendered.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from orchestrator.core.exceptions import ContextDiscoveryError

BUILTIN_EXCLUDED_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "vendor", "__pycache__",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox", ".nox", ".eggs", "build",
    "dist", "site-packages", ".idea", ".vscode",
})
_SECRET_NAME = re.compile(
    r"^\.env(\..*)?$|\.(pem|key|p12|pfx|jks|keystore)$|^id_(rsa|dsa|ecdsa|ed25519)"
    r"|^\.(npmrc|pypirc|netrc|pgpass)$|^credentials(\..*)?$|^secrets?\.(ya?ml|json|toml)$",
    re.IGNORECASE,
)
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
HEAD_BYTES = 8192
_HEADING = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


def is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME.search(name))


@dataclass(frozen=True, slots=True)
class FoundFile:
    path: Path  # as found (inside the project root), not symlink-resolved
    relative: str  # POSIX path relative to the project root
    size: int


@dataclass(slots=True)
class WalkResult:
    files: list[FoundFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ProjectFiles:
    def __init__(
        self, project_root: Path, *, exclude_dirs: Iterable[str] = (), max_files: int,
        max_file_bytes: int,
    ) -> None:
        self.root = project_root.resolve()
        self.excluded = BUILTIN_EXCLUDED_DIRS | frozenset(exclude_dirs)
        self.max_files = max_files
        self.max_file_bytes = max_file_bytes

    # --- roots and paths ---------------------------------------------------------------

    def configured(self, relative: str) -> Path:
        """A configured path (already syntactically checked by config). Fatal if it
        resolves outside the project root (e.g. through a symlink)."""
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root):
            raise ContextDiscoveryError(
                f"configured path '{relative}' resolves outside the project root {self.root}",
                path=path,
            )
        return path

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def rejection(self, path: Path) -> str | None:
        """Why `path` (absolute, normalized) cannot be a candidate or be listed."""
        if not path.is_relative_to(self.root) or not path.resolve().is_relative_to(self.root):
            return "resolves outside the project root"
        parts = path.relative_to(self.root).parts
        if any(part in self.excluded for part in parts):
            return "inside an excluded directory"
        if parts and is_secret_name(parts[-1]):
            return "looks like a secret file"
        return None

    def check_file(self, path: Path) -> tuple[FoundFile | None, str | None]:
        """(file, None) when `path` is an acceptable candidate file, else (None, reason)."""
        reason = self.rejection(path)
        if reason is not None:
            return None, reason
        if not path.is_file():
            return None, "not a regular file"
        size = path.stat().st_size
        if size > self.max_file_bytes:
            return None, f"larger than max_file_bytes ({size} > {self.max_file_bytes})"
        return FoundFile(path, self.relative(path), size), None

    # --- walking -------------------------------------------------------------------------

    def walk(self, start: Path, suffixes: frozenset[str] | None = None) -> WalkResult:
        """Files under `start` (a directory inside the root), sorted, bounded, pruned."""
        result = WalkResult()
        visited = 0
        stack = [start]
        while stack:
            directory = stack.pop()
            try:
                entries = sorted(directory.iterdir(), key=lambda p: p.name)
            except OSError as exc:
                result.warnings.append(f"cannot list {self.relative(directory)}: {exc.strerror}")
                continue
            subdirs: list[Path] = []
            for entry in entries:
                if entry.name.startswith(".") or entry.name in self.excluded:
                    continue
                if entry.is_dir():
                    if not entry.is_symlink():
                        subdirs.append(entry)
                    continue
                if suffixes is not None and entry.suffix.lower() not in suffixes:
                    continue
                if visited >= self.max_files:
                    result.warnings.append(
                        f"stopped after max_files={self.max_files} under {self.relative(start)}"
                    )
                    return result
                visited += 1
                found, reason = self.check_file(entry)
                if found is not None:
                    result.files.append(found)
                elif reason != "looks like a secret file":
                    result.warnings.append(f"skipped {self.relative(entry)}: {reason}")
            stack.extend(reversed(subdirs))  # depth-first, ascending
        return result

    # --- metadata ----------------------------------------------------------------------

    @staticmethod
    def head(found: FoundFile) -> str:
        """First bytes of a Markdown file (for title/status only); '' otherwise."""
        if found.path.suffix.lower() not in MARKDOWN_SUFFIXES:
            return ""
        try:
            with found.path.open("rb") as handle:
                return handle.read(HEAD_BYTES).decode("utf-8", errors="replace")
        except OSError:
            return ""

    @staticmethod
    def title(found: FoundFile, head: str) -> str:
        """First Markdown `# heading` in `head`, else the file name."""
        match = _HEADING.search(head)
        return match.group(1) if match else found.path.name

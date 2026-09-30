"""Global Library loading (V1): discover -> read -> parse -> validate, per file.

Layout of a library root (the Harness installation directory by default):

    <root>/policies/*.md   <root>/guidelines/*.md   <root>/rules/*.md
    <root>/skills/*.md     <root>/specialties/*.md

Each file is Markdown with YAML front matter:

    ---
    version: 1
    id: laravel
    type: skill
    ...
    ---
    <body>

Safety rules (the library is trusted, versioned content, but still validated):
- discovery lists the five known directories only; nothing is read from a path
  supplied by a caller or by a file;
- every directory and file must resolve inside its expected directory, so a
  symlink cannot pull in content from elsewhere (`../`, absolute targets);
- only regular `*.md` files are accepted; hidden entries (`.gitkeep`) are
  ignored; subdirectories or other files fail the load (no silent skipping);
- files are size-limited, decoded as UTF-8 and parsed with a safe YAML loader;
  the body is kept as inert text: nothing is executed, evaluated or rendered.

The load fails fast on the first problem, in a stable order (type order, then
file name), so the same broken library always reports the same error.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from orchestrator.config import default_harness_root
from orchestrator.core.exceptions import (
    ArtifactParseError,
    ArtifactValidationError,
    HarnessPathError,
    LibraryStructureError,
)
from orchestrator.library.models import (
    DIRECTORY_BY_TYPE,
    METADATA_MODEL_BY_TYPE,
    SCHEMA_VERSION,
    Artifact,
    ArtifactType,
)
from orchestrator.utils.files import read_text
from orchestrator.utils.yaml_loader import load_yaml

LIBRARY_ROOT_ENV = "HARNESS_LIBRARY_ROOT"
ARTIFACT_SUFFIX = ".md"
MAX_ARTIFACT_BYTES = 256 * 1024
_FENCE = "---"


# --- location -----------------------------------------------------------------


def resolve_library_root(
    explicit: Path | None = None, environ: Mapping[str, str] | None = None
) -> Path:
    """Locate the Global Library. Precedence: explicit > $HARNESS_LIBRARY_ROOT >
    the Harness installation directory (next to the `orchestrator` package).

    Deliberately independent of the harness root (`--root` / $HARNESS_ROOT): a
    consumer project points the Harness at its own `config/` and still inherits
    the one library of the installation, without copying it.

    Raises:
        LibraryStructureError: the chosen root is not a directory.
    """
    env = os.environ if environ is None else environ
    if explicit is not None:
        root, source = explicit, "explicit path"
    elif env.get(LIBRARY_ROOT_ENV):
        root, source = Path(env[LIBRARY_ROOT_ENV]), f"${LIBRARY_ROOT_ENV}"
    else:
        root, source = default_harness_root(), "package location"
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise LibraryStructureError(f"library root (from {source}) is not a directory", path=root)
    return root


# --- discovery ----------------------------------------------------------------


def _ensure_within(container: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(container):
        raise LibraryStructureError(f"resolves outside {container} (to {resolved})", path=path)
    return resolved


def _discover(root: Path, artifact_type: ArtifactType) -> Iterator[Path]:
    """Artifact files of one type, sorted by name. `root` must already be resolved."""
    type_dir = root / DIRECTORY_BY_TYPE[artifact_type]
    if not type_dir.is_dir():
        raise LibraryStructureError(
            f"missing '{DIRECTORY_BY_TYPE[artifact_type]}/' directory for {artifact_type} "
            "artifacts (it may be empty, but it must exist)",
            path=type_dir,
        )
    resolved_dir = _ensure_within(root, type_dir)
    for entry in sorted(type_dir.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue
        _ensure_within(resolved_dir, entry)
        if not entry.is_file() or entry.suffix != ARTIFACT_SUFFIX:
            raise LibraryStructureError(
                f"unexpected entry: only '*{ARTIFACT_SUFFIX}' artifact files are allowed in "
                f"'{DIRECTORY_BY_TYPE[artifact_type]}/'",
                path=entry,
            )
        yield entry


# --- parsing ------------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ArtifactParseError(f"cannot stat file: {exc}", path=path) from exc
    if size > MAX_ARTIFACT_BYTES:
        raise ArtifactParseError(
            f"file is {size} bytes; the limit is {MAX_ARTIFACT_BYTES}", path=path
        )
    try:
        return read_text(path).removeprefix("﻿")
    except HarnessPathError as exc:
        raise ArtifactParseError(str(exc), path=path) from exc


def split_front_matter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    """Split `---` fenced YAML front matter from the Markdown body."""
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != _FENCE:
        raise ArtifactParseError("missing front matter: the first line must be '---'", path=path)
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == _FENCE), None)
    if end is None:
        raise ArtifactParseError("front matter is not closed by a '---' line", path=path)
    try:
        data = load_yaml("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise ArtifactParseError(f"invalid YAML front matter: {exc}", path=path) from exc
    if not isinstance(data, dict):
        found = "nothing" if data is None else type(data).__name__
        raise ArtifactParseError(f"front matter must be a mapping, got {found}", path=path)
    return data, "\n".join(lines[end + 1 :]).strip()


# --- validation -----------------------------------------------------------------


def _format_errors(exc: PydanticValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in error['loc']) or '<root>'}: {error['msg']}"
        for error in exc.errors()
    )


def parse_artifact(text: str, *, path: Path, root: Path, expected: ArtifactType) -> Artifact:
    """Parse and validate one artifact that was found in `expected`'s directory."""
    data, body = split_front_matter(text, path)

    # Checked before the schema so the message names the real problem.
    version = data.get("version")
    if version != SCHEMA_VERSION or isinstance(version, bool):
        raise ArtifactValidationError(
            f"unsupported schema version {version!r} (supported: {SCHEMA_VERSION})", path=path
        )
    declared = data.get("type")
    if declared not in {t.value for t in ArtifactType}:
        raise ArtifactValidationError(
            f"invalid type {declared!r}; expected one of {[t.value for t in ArtifactType]}",
            path=path,
        )
    if declared != expected.value:
        raise ArtifactValidationError(
            f"type '{declared}' does not match its directory "
            f"'{DIRECTORY_BY_TYPE[expected]}/' (expected '{expected}')",
            path=path,
        )

    try:
        metadata = METADATA_MODEL_BY_TYPE[expected].model_validate(data)
    except PydanticValidationError as exc:
        raise ArtifactValidationError(_format_errors(exc), path=path) from exc
    if not body:
        raise ArtifactValidationError("artifact body is empty", path=path)
    return Artifact(metadata=metadata, body=body, source=path.relative_to(root).as_posix())


def load_artifacts(root: Path) -> tuple[Artifact, ...]:
    """Discover and load every artifact under `root`, in a stable order.

    Cross-artifact invariants (duplicate ids, references) are checked by
    `GlobalLibrary` when it indexes the result.
    """
    if not root.is_dir():
        raise LibraryStructureError("library root is not a directory", path=root)
    resolved_root = root.resolve()
    return tuple(
        parse_artifact(_read(path), path=path, root=resolved_root, expected=artifact_type)
        for artifact_type in ArtifactType
        for path in _discover(resolved_root, artifact_type)
    )

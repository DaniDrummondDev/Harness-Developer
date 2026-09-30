"""Builders for Global Library test fixtures (V1)."""

from __future__ import annotations

from pathlib import Path

DIRECTORY = {
    "policy": "policies",
    "guideline": "guidelines",
    "rule": "rules",
    "skill": "skills",
    "specialty": "specialties",
}


def artifact_text(
    artifact_id: str,
    artifact_type: str,
    *,
    applies_to: str = "  always: true",
    extra: str = "",
    body: str = "Body.",
) -> str:
    """A valid artifact file; each test tweaks one aspect."""
    return (
        "---\n"
        "version: 1\n"
        f"id: {artifact_id}\n"
        f"type: {artifact_type}\n"
        f"name: {artifact_id.title()}\n"
        f"description: About {artifact_id}.\n"
        "applies_to:\n"
        f"{applies_to}\n"
        f"{extra}"
        "---\n"
        f"{body}\n"
    )


def write_artifact(
    root: Path, artifact_id: str, artifact_type: str, *, filename: str | None = None,
    directory: str | None = None, **kwargs: str,
) -> Path:
    """Write a valid artifact into its type directory (overridable) and return its path."""
    path = root / (directory or DIRECTORY[artifact_type]) / (filename or f"{artifact_id}.md")
    path.write_text(artifact_text(artifact_id, artifact_type, **kwargs), encoding="utf-8")
    return path

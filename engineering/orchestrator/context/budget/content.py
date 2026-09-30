"""Candidate content materialization for the budget (V1.3): reference -> safe text.

Discovery (V1.1) keeps candidates as references; the budget needs their real
size, and the selected items need their text. `ContextContentLoader` is the one
place that turns a `CandidateReference` into text, per store:

    store     source of the text                    safety
    project   the file under the project root       ProjectFiles.check_file (the V1.1 rules:
                                                    contained after resolving symlinks, no
                                                    excluded dir, no secret-looking name,
                                                    regular file, <= max_file_bytes), then:
                                                    bounded read, NUL byte -> binary,
                                                    strict UTF-8 (else not text)
    library   GlobalLibrary.get(type, id).body       already loaded and validated by the
                                                    library loader: no second read or parse
    memory    metadata["excerpt"] (<= 280 chars)     already checked when stored; the
                                                    MemoryProvider has no get-by-id

A failure is a value (`LoadedContent.problem`), never an exception: the budget
decides what a missing REQUIRED means. Nothing is executed, evaluated or
rendered; the only filesystem access is one bounded read of an accepted file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orchestrator.context.files import ProjectFiles
from orchestrator.context.models import ContextCandidate, ReferenceStore
from orchestrator.core.exceptions import HarnessError
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.models import ArtifactType

_BOM = "﻿"


@dataclass(frozen=True, slots=True)
class LoadedContent:
    text: str | None = None
    problem: str | None = None  # why there is no text


class ContentLoader(Protocol):
    """What the budget needs: a candidate's text, or why there is none."""

    def load(self, candidate: ContextCandidate) -> LoadedContent: ...


class ContextContentLoader:
    def __init__(self, files: ProjectFiles, library: GlobalLibrary) -> None:
        self._files = files
        self._library = library

    def load(self, candidate: ContextCandidate) -> LoadedContent:
        store = candidate.reference.store
        if store is ReferenceStore.PROJECT:
            return self._project_file(candidate.reference.path)
        if store is ReferenceStore.LIBRARY:
            return self._library_artifact(candidate)
        excerpt = candidate.metadata.get("excerpt")
        if isinstance(excerpt, str):
            return LoadedContent(text=excerpt)
        return LoadedContent(problem="memory candidate has no excerpt")

    def _project_file(self, relative: str) -> LoadedContent:
        # normpath collapses `..` so an escaping reference fails the containment check.
        path = Path(os.path.normpath(self._files.root / relative))
        found, reason = self._files.check_file(path)
        if found is None:
            return LoadedContent(problem=f"project file '{relative}': {reason}")
        limit = self._files.max_file_bytes
        try:
            with found.path.open("rb") as handle:
                data = handle.read(limit + 1)
        except OSError as exc:
            return LoadedContent(problem=f"project file '{relative}': {exc.strerror}")
        if len(data) > limit:  # grew after the size check
            return LoadedContent(problem=f"project file '{relative}': larger than max_file_bytes")
        if b"\x00" in data:
            return LoadedContent(problem=f"project file '{relative}': binary content")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return LoadedContent(problem=f"project file '{relative}': not UTF-8 text")
        return LoadedContent(text=text.removeprefix(_BOM))

    def _library_artifact(self, candidate: ContextCandidate) -> LoadedContent:
        artifact_id = candidate.metadata.get("artifact_id")
        if not isinstance(artifact_id, str):
            return LoadedContent(problem="library candidate has no artifact_id")
        try:
            artifact = self._library.get(ArtifactType(candidate.kind.value), artifact_id)
        except (ValueError, HarnessError) as exc:  # not a library kind / not in this library
            return LoadedContent(problem=f"library artifact '{candidate.id}': {exc}")
        if artifact.source != candidate.reference.path:
            return LoadedContent(
                problem=f"library artifact '{candidate.id}' is not at '{candidate.reference.path}'"
            )
        return LoadedContent(text=artifact.body)

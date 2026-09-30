"""V1.3 content materialization: reference -> safe text (project files, library, memory)."""

from __future__ import annotations

from pathlib import Path

import pytest
from classification_helpers import candidate
from library_helpers import write_artifact

from orchestrator.context.budget.content import ContextContentLoader, LoadedContent
from orchestrator.context.files import ProjectFiles
from orchestrator.context.models import (
    CandidateKind,
    CandidateReference,
    ContextCandidate,
    Provenance,
    ReferenceStore,
)
from orchestrator.library.library import GlobalLibrary

K = CandidateKind


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def loader(project: Path, library_root: Path, max_file_bytes: int = 1000) -> ContextContentLoader:
    files = ProjectFiles(project, max_files=100, max_file_bytes=max_file_bytes)
    return ContextContentLoader(files, GlobalLibrary.load(library_root))


def source(path: str) -> ContextCandidate:
    return candidate(K.SOURCE_CODE, path)


def write(path: Path, data: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


# --- project files ------------------------------------------------------------------------------


def test_normal_file_is_loaded_and_measured_in_characters(project: Path, library_root: Path
                                                          ) -> None:
    write(project / "src" / "tax.py", "﻿TAXA = 'ação'\n")
    loaded = loader(project, library_root).load(source("src/tax.py"))
    assert loaded == LoadedContent(text="TAXA = 'ação'\n")  # BOM stripped
    assert len(loaded.text or "") == 14  # code points, not the 16 UTF-8 bytes


def test_missing_file(project: Path, library_root: Path) -> None:
    loaded = loader(project, library_root).load(source("src/gone.py"))
    assert loaded.text is None and "not a regular file" in (loaded.problem or "")


@pytest.mark.parametrize("path", ["../outside.txt", "src/../../outside.txt", "/etc/hostname"])
def test_path_traversal_is_rejected(project: Path, library_root: Path, path: str) -> None:
    write(project.parent / "outside.txt", "secret-ish")
    loaded = loader(project, library_root).load(source(path))
    assert loaded.text is None and "outside the project root" in (loaded.problem or "")


def test_symlink_escaping_the_project_is_rejected(project: Path, library_root: Path) -> None:
    target = write(project.parent / "elsewhere.py", "print('x')")
    (project / "link.py").symlink_to(target)
    loaded = loader(project, library_root).load(source("link.py"))
    assert loaded.text is None and "outside the project root" in (loaded.problem or "")


def test_symlink_inside_the_project_is_followed(project: Path, library_root: Path) -> None:
    write(project / "real.py", "x = 1\n")
    (project / "alias.py").symlink_to(project / "real.py")
    assert loader(project, library_root).load(source("alias.py")).text == "x = 1\n"


@pytest.mark.parametrize("name", [".env", ".env.local", "id_rsa", "server.pem", "secrets.yaml",
                                  "credentials.json"])
def test_secret_files_are_never_read(project: Path, library_root: Path, name: str,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    write(project / name, "API_KEY=abc")
    opened: list[Path] = []
    real_open = Path.open
    monkeypatch.setattr(Path, "open", lambda self, *a, **k: opened.append(self) or real_open(
        self, *a, **k))
    loaded = loader(project, library_root).load(source(name))
    assert loaded.text is None and "secret" in (loaded.problem or "")
    assert opened == []


def test_excluded_directories_are_rejected(project: Path, library_root: Path) -> None:
    write(project / "node_modules" / "lib" / "index.js", "module.exports = 1")
    loaded = loader(project, library_root).load(source("node_modules/lib/index.js"))
    assert "excluded directory" in (loaded.problem or "")


def test_binary_content_is_never_text(project: Path, library_root: Path) -> None:
    write(project / "logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    loaded = loader(project, library_root).load(source("logo.png"))
    assert loaded == LoadedContent(problem="project file 'logo.png': binary content")


def test_non_utf8_content_is_rejected(project: Path, library_root: Path) -> None:
    write(project / "latin1.txt", "ação".encode("latin-1"))
    loaded = loader(project, library_root).load(source("latin1.txt"))
    assert loaded.problem == "project file 'latin1.txt': not UTF-8 text"


def test_large_file_is_rejected_without_reading(project: Path, library_root: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    write(project / "big.txt", "x" * 101)
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("must not open"))
    loaded = loader(project, library_root, max_file_bytes=100).load(source("big.txt"))
    assert "larger than max_file_bytes (101 > 100)" in (loaded.problem or "")


def test_file_that_grows_after_the_size_check_is_rejected(project: Path, library_root: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    path = write(project / "log.txt", "x" * 10)
    files = ProjectFiles(project, max_files=10, max_file_bytes=50)
    real_check = files.check_file

    def check_then_grow(p: Path):  # type: ignore[no-untyped-def]
        found = real_check(p)
        path.write_text("x" * 80, encoding="utf-8")
        return found

    monkeypatch.setattr(files, "check_file", check_then_grow)
    loaded = ContextContentLoader(files, GlobalLibrary.load(library_root)).load(source("log.txt"))
    assert loaded.problem == "project file 'log.txt': larger than max_file_bytes"


def test_loading_does_not_depend_on_cwd(project: Path, library_root: Path, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    write(project / "src" / "a.py", "a = 1\n")
    elsewhere = tmp_path / "elsewhere"
    write(elsewhere / "src" / "a.py", "WRONG\n")
    monkeypatch.chdir(elsewhere)
    assert loader(project, library_root).load(source("src/a.py")).text == "a = 1\n"


# --- library and memory -------------------------------------------------------------------------


def _library_candidate(kind: CandidateKind, artifact_id: str, source_path: str) -> ContextCandidate:
    return ContextCandidate(
        id=f"{kind}/{artifact_id}", kind=kind, title=artifact_id,
        reference=CandidateReference(store=ReferenceStore.LIBRARY, path=source_path),
        provenance=(Provenance(discoverer="library", reason="test"),),
        metadata={"artifact_id": artifact_id},
    )


def test_library_artifact_body_comes_from_the_loaded_library(project: Path,
                                                             library_root: Path) -> None:
    write_artifact(library_root, "secrets", "policy", body="Never commit secrets.")
    content = loader(project, library_root).load(
        _library_candidate(K.POLICY, "secrets", "policies/secrets.md"))
    assert content.text == "Never commit secrets."  # body only: no front matter re-parsing


def test_library_artifact_not_in_the_library(project: Path, library_root: Path) -> None:
    loaded = loader(project, library_root).load(
        _library_candidate(K.SKILL, "ghost", "skills/ghost.md"))
    assert loaded.text is None and "ghost" in (loaded.problem or "")


def test_library_reference_must_match_the_artifact_source(project: Path,
                                                          library_root: Path) -> None:
    write_artifact(library_root, "python", "skill")
    loaded = loader(project, library_root).load(
        _library_candidate(K.SKILL, "python", "../../etc/passwd"))
    assert loaded.text is None and "is not at" in (loaded.problem or "")


def test_library_candidate_without_artifact_id(project: Path, library_root: Path) -> None:
    bare = candidate(K.GUIDELINE, "coding")  # helper metadata has no artifact_id
    assert loader(project, library_root).load(bare).problem == (
        "library candidate has no artifact_id")


def test_memory_uses_the_excerpt_it_already_carries(project: Path, library_root: Path) -> None:
    memory = candidate(K.MEMORY, "m-1", metadata={"excerpt": "Rounding is half-even."})
    assert loader(project, library_root).load(memory).text == "Rounding is half-even."
    assert loader(project, library_root).load(candidate(K.MEMORY, "m-2")).problem == (
        "memory candidate has no excerpt")

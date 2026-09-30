"""V1.1 context discovery: candidate contracts and safe project file access."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.context.files import HEAD_BYTES, ProjectFiles, is_secret_name
from orchestrator.context.models import (
    UNSUPPORTED_SOURCES,
    CandidateKind,
    CandidateReference,
    ContextCandidate,
    ContextDiscoveryResult,
    Provenance,
    ReferenceStore,
    SourceReport,
    SourceStatus,
)
from orchestrator.core.exceptions import ContextDiscoveryError, HarnessError
from orchestrator.intake import normalize_request


def make_files(root: Path, **kwargs: int) -> ProjectFiles:
    return ProjectFiles(root, exclude_dirs=("generated",),
                        max_files=kwargs.get("max_files", 100),
                        max_file_bytes=kwargs.get("max_file_bytes", 10_000))


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- candidate contract -------------------------------------------------------------------


def _candidate(**overrides: object) -> ContextCandidate:
    data: dict[str, object] = {
        "id": "adr/docs/adr/0001-x.md",
        "kind": CandidateKind.ADR,
        "title": "ADR-0001",
        "reference": CandidateReference(store=ReferenceStore.PROJECT, path="docs/adr/0001-x.md"),
        "provenance": (Provenance(discoverer="adrs", reason="ADR under 'docs/adr'"),),
        "metadata": {"status": "Accepted", "size_bytes": 10},
    }
    data.update(overrides)
    return ContextCandidate.model_validate(data)


def test_candidate_is_immutable_and_serializable() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError):
        candidate.title = "other"  # type: ignore[misc]
    dumped = candidate.model_dump(mode="json")
    assert dumped["kind"] == "adr"
    assert dumped["reference"] == {"store": "project", "path": "docs/adr/0001-x.md"}
    assert ContextCandidate.model_validate(dumped) == candidate
    assert str(candidate.reference) == "project:docs/adr/0001-x.md"


def test_candidate_has_no_classification_or_budget_fields() -> None:
    fields = set(ContextCandidate.model_fields)
    assert fields == {"id", "kind", "title", "reference", "provenance", "metadata"}
    for forbidden in ("classification", "relevance", "score", "required", "tokens"):
        with pytest.raises(ValidationError):
            _candidate(**{forbidden: "REQUIRED"})


def test_candidate_requires_provenance_and_identity() -> None:
    with pytest.raises(ValidationError):
        _candidate(provenance=())
    with pytest.raises(ValidationError):
        _candidate(id="")


def test_kinds_are_the_supported_sources_only() -> None:
    assert [k.value for k in CandidateKind] == [
        "policy", "guideline", "rule", "skill", "specialty", "instructions", "adr", "doc",
        "source", "memory",
    ]
    assert set(UNSUPPORTED_SOURCES) == {
        "task_contract", "sprint", "git", "previous_runs", "releases", "findings",
    }


def test_result_flattens_warnings_per_source() -> None:
    request = normalize_request(source="cli", instruction="x")
    result = ContextDiscoveryResult(request=request, candidates=(), sources=(
        SourceReport(discoverer="adrs", status=SourceStatus.OK, candidates=0,
                     warnings=("'docs/adr' does not exist",)),
        SourceReport(discoverer="memory", status=SourceStatus.SKIPPED, candidates=0,
                     warnings=("memory is disabled",)),
    ))
    assert result.warnings == ("adrs: 'docs/adr' does not exist", "memory: memory is disabled")
    assert result.model_dump(mode="json")["request"]["instruction"] == "x"


def test_context_error_is_a_harness_error() -> None:
    assert issubclass(ContextDiscoveryError, HarnessError)


# --- configured roots ------------------------------------------------------------------------


def test_configured_path_escaping_through_symlink_is_fatal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "outside").mkdir()
    (project / "docs").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(ContextDiscoveryError, match="resolves outside the project root"):
        make_files(project).configured("docs")


def test_root_is_canonicalized(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    assert make_files(tmp_path / "link").root == (tmp_path / "real").resolve()


# --- walking ---------------------------------------------------------------------------------


def test_walk_is_sorted_and_prunes_hidden_excluded_and_secret_entries(tmp_path: Path) -> None:
    for rel in ("docs/b.md", "docs/a.md", "docs/sub/c.md", "docs/.hidden.md", "docs/.git/x.md",
                "docs/node_modules/y.md", "docs/generated/z.md", "docs/.env", "docs/id_rsa.md",
                "docs/notes.bin"):
        touch(tmp_path / rel)
    files = make_files(tmp_path)
    result = files.walk(tmp_path / "docs", frozenset({".md"}))
    assert [f.relative for f in result.files] == ["docs/a.md", "docs/b.md", "docs/sub/c.md"]
    assert result.warnings == []


def test_walk_order_does_not_depend_on_creation_order(tmp_path: Path) -> None:
    for name in ("z.md", "m.md", "a.md"):
        touch(tmp_path / "one" / name)
    for name in ("a.md", "m.md", "z.md"):
        touch(tmp_path / "two" / name)
    files = make_files(tmp_path)
    one = [f.path.name for f in files.walk(tmp_path / "one").files]
    two = [f.path.name for f in files.walk(tmp_path / "two").files]
    assert one == two == ["a.md", "m.md", "z.md"]


def test_walk_does_not_follow_symlinked_directories(tmp_path: Path) -> None:
    touch(tmp_path / "outside" / "leak.md")
    project = tmp_path / "project"
    touch(project / "docs" / "ok.md")
    (project / "docs" / "linked").symlink_to(tmp_path / "outside", target_is_directory=True)
    result = make_files(project).walk(project / "docs")
    assert [f.relative for f in result.files] == ["docs/ok.md"]


def test_walk_skips_symlinked_file_pointing_outside(tmp_path: Path) -> None:
    outside = touch(tmp_path / "outside.md")
    project = tmp_path / "project"
    touch(project / "docs" / "ok.md")
    (project / "docs" / "evil.md").symlink_to(outside)
    result = make_files(project).walk(project / "docs")
    assert [f.relative for f in result.files] == ["docs/ok.md"]
    assert result.warnings == ["skipped docs/evil.md: resolves outside the project root"]


def test_walk_skips_oversized_files_without_reading(tmp_path: Path) -> None:
    touch(tmp_path / "docs" / "big.md", "x" * 101)
    touch(tmp_path / "docs" / "small.md", "x")
    result = make_files(tmp_path, max_file_bytes=100).walk(tmp_path / "docs")
    assert [f.relative for f in result.files] == ["docs/small.md"]
    assert "larger than max_file_bytes" in result.warnings[0]


def test_walk_stops_at_max_files(tmp_path: Path) -> None:
    for index in range(5):
        touch(tmp_path / "docs" / f"{index}.md")
    result = make_files(tmp_path, max_files=3).walk(tmp_path / "docs")
    assert [f.path.name for f in result.files] == ["0.md", "1.md", "2.md"]
    assert result.warnings == ["stopped after max_files=3 under docs"]


@pytest.mark.parametrize(
    "name", [".env", ".env.local", "server.pem", "tls.key", "id_rsa", "id_ed25519.pub",
             ".npmrc", "credentials.json", "secrets.yaml", "store.jks"],
)
def test_secret_names(name: str) -> None:
    assert is_secret_name(name)


@pytest.mark.parametrize("name", ["README.md", "keys.py", "environment.md", "secret_sauce.md"])
def test_non_secret_names(name: str) -> None:
    assert not is_secret_name(name)


def test_head_reads_only_a_bounded_prefix_of_markdown(tmp_path: Path) -> None:
    found, _ = make_files(tmp_path, max_file_bytes=10**6).check_file(
        touch(tmp_path / "doc.md", "# Title\n" + "x" * (HEAD_BYTES * 2))
    )
    assert found is not None
    head = ProjectFiles.head(found)
    assert len(head) == HEAD_BYTES
    assert ProjectFiles.title(found, head) == "Title"
    source, _ = make_files(tmp_path).check_file(touch(tmp_path / "code.py", "# not a title"))
    assert source is not None and ProjectFiles.head(source) == ""
    assert ProjectFiles.title(source, "") == "code.py"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can list any directory")
def test_unlistable_directory_is_a_warning(tmp_path: Path) -> None:
    locked = tmp_path / "docs" / "locked"
    touch(locked / "a.md")
    locked.chmod(0)
    try:
        result = make_files(tmp_path).walk(tmp_path / "docs")
    finally:
        locked.chmod(0o755)
    assert result.files == []
    assert result.warnings[0].startswith("cannot list docs/locked")

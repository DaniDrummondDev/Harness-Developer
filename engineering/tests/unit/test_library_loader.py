"""V1 Global Library: discovery, parsing, validation and path safety."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from library_helpers import artifact_text, write_artifact

from orchestrator.config import default_harness_root
from orchestrator.core.exceptions import (
    ArtifactNotFoundError,
    ArtifactParseError,
    ArtifactValidationError,
    HarnessError,
    LibraryError,
    LibraryStructureError,
)
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.loader import (
    LIBRARY_ROOT_ENV,
    MAX_ARTIFACT_BYTES,
    load_artifacts,
    resolve_library_root,
)
from orchestrator.library.models import (
    ArtifactType,
    Authority,
    SpecialtyMetadata,
)

# --- loading --------------------------------------------------------------------------


def test_valid_library_with_every_type(library_root: Path) -> None:
    for artifact_type in ("policy", "guideline", "rule", "skill"):
        write_artifact(library_root, f"a-{artifact_type}", artifact_type)
    write_artifact(library_root, "domain", "specialty",
                   extra="skills: [a-skill]\nrules: [a-rule]\n")

    library = GlobalLibrary.load(library_root)

    assert [a.key for a in library.artifacts()] == [
        "policy/a-policy", "guideline/a-guideline", "rule/a-rule",
        "skill/a-skill", "specialty/domain",
    ]
    skill = library.get(ArtifactType.SKILL, "a-skill")
    assert skill.body == "Body."
    assert skill.source == "skills/a-skill.md"
    assert skill.metadata.version == 1
    specialty = library.get(ArtifactType.SPECIALTY, "domain").metadata
    assert isinstance(specialty, SpecialtyMetadata)
    assert specialty.skills == ("a-skill",) and specialty.rules == ("a-rule",)


def test_empty_library_is_allowed(library_root: Path) -> None:
    library = GlobalLibrary.load(library_root)
    assert library.artifacts() == ()
    assert all(library.by_type(t) == () for t in ArtifactType)


def test_order_is_stable_and_independent_of_creation_order(library_root: Path) -> None:
    for name in ("zeta", "alpha", "mid"):
        write_artifact(library_root, name, "skill")
    write_artifact(library_root, "zz-policy", "policy")

    first = [a.key for a in GlobalLibrary.load(library_root).artifacts()]
    second = [a.key for a in GlobalLibrary.load(library_root).artifacts()]

    assert first == second == [
        "policy/zz-policy", "skill/alpha", "skill/mid", "skill/zeta",
    ]


def test_same_id_in_different_types_are_distinct_artifacts(library_root: Path) -> None:
    write_artifact(library_root, "testing", "skill")
    write_artifact(library_root, "testing", "guideline")
    library = GlobalLibrary.load(library_root)
    assert {a.key for a in library.artifacts()} == {"skill/testing", "guideline/testing"}


def test_authority_is_derived_from_type_not_declared(library_root: Path) -> None:
    write_artifact(library_root, "x", "guideline", extra="authority: mandatory\n")
    with pytest.raises(ArtifactValidationError, match="authority"):
        GlobalLibrary.load(library_root)


def test_hidden_entries_are_ignored(library_root: Path) -> None:
    (library_root / "skills" / ".gitkeep").write_text("")
    assert GlobalLibrary.load(library_root).artifacts() == ()


def test_crlf_and_bom_are_accepted(library_root: Path) -> None:
    text = "﻿" + artifact_text("win", "skill").replace("\n", "\r\n")
    (library_root / "skills" / "win.md").write_bytes(text.encode("utf-8"))
    assert GlobalLibrary.load(library_root).get(ArtifactType.SKILL, "win").body == "Body."


def test_get_unknown_artifact(library_root: Path) -> None:
    with pytest.raises(ArtifactNotFoundError, match="no skill with id 'nope'"):
        GlobalLibrary.load(library_root).get(ArtifactType.SKILL, "nope")


def test_library_errors_are_harness_errors() -> None:
    for error in (LibraryStructureError, ArtifactParseError, ArtifactValidationError,
                  ArtifactNotFoundError):
        assert issubclass(error, LibraryError)
        assert issubclass(error, HarnessError)


# --- structure ------------------------------------------------------------------------


def test_missing_root(tmp_path: Path) -> None:
    with pytest.raises(LibraryStructureError, match="not a directory"):
        GlobalLibrary.load(tmp_path / "absent")


def test_missing_type_directory(library_root: Path) -> None:
    (library_root / "rules").rmdir()
    with pytest.raises(LibraryStructureError, match="missing 'rules/' directory"):
        GlobalLibrary.load(library_root)


@pytest.mark.parametrize("name", ["notes.txt", "skill.yaml", "README"])
def test_non_markdown_file_is_rejected(library_root: Path, name: str) -> None:
    (library_root / "skills" / name).write_text("x")
    with pytest.raises(LibraryStructureError, match=r"only '\*\.md' artifact files"):
        GlobalLibrary.load(library_root)


def test_subdirectory_is_rejected(library_root: Path) -> None:
    (library_root / "skills" / "nested").mkdir()
    with pytest.raises(LibraryStructureError, match="unexpected entry"):
        GlobalLibrary.load(library_root)


# --- path safety ------------------------------------------------------------------------


def test_symlink_to_file_outside_root_is_rejected(library_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text(artifact_text("stolen", "skill"))
    (library_root / "skills" / "stolen.md").symlink_to(outside)
    with pytest.raises(LibraryStructureError, match="resolves outside"):
        GlobalLibrary.load(library_root)


def test_symlink_traversing_with_dotdot_is_rejected(library_root: Path) -> None:
    write_artifact(library_root, "coding", "guideline")
    (library_root / "skills" / "coding.md").symlink_to(Path("..") / "guidelines" / "coding.md")
    with pytest.raises(LibraryStructureError, match="resolves outside"):
        GlobalLibrary.load(library_root)


def test_symlinked_type_directory_outside_root_is_rejected(
    library_root: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (library_root / "skills").rmdir()
    (library_root / "skills").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(LibraryStructureError, match="resolves outside"):
        GlobalLibrary.load(library_root)


def test_oversized_file_is_rejected_before_reading(library_root: Path) -> None:
    body = "x" * (MAX_ARTIFACT_BYTES + 1)
    write_artifact(library_root, "huge", "skill", body=body)
    with pytest.raises(ArtifactParseError, match="limit"):
        GlobalLibrary.load(library_root)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_unreadable_file(library_root: Path) -> None:
    path = write_artifact(library_root, "secret", "skill")
    path.chmod(0)
    try:
        with pytest.raises(ArtifactParseError, match="cannot read"):
            GlobalLibrary.load(library_root)
    finally:
        path.chmod(0o644)


def test_invalid_utf8_is_a_parse_error(library_root: Path) -> None:
    (library_root / "skills" / "bin.md").write_bytes(b"---\n\xff\xfe\n---\nx\n")
    with pytest.raises(ArtifactParseError, match="cannot read"):
        GlobalLibrary.load(library_root)


def test_yaml_tags_are_never_executed(library_root: Path, tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    extra = f"x: !!python/object/apply:os.system ['touch {marker}']\n"
    write_artifact(library_root, "evil", "skill", extra=extra)
    with pytest.raises(ArtifactParseError, match="invalid YAML"):
        GlobalLibrary.load(library_root)
    assert not marker.exists()


# --- parsing ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("# just markdown\n", "missing front matter"),
        ("", "missing front matter"),
        ("---\nid: x\n", "not closed"),
        ("---\n---\nbody\n", "must be a mapping, got nothing"),
        ("---\n- a\n- b\n---\nbody\n", "must be a mapping, got list"),
        ("---\nid: [unclosed\n---\nbody\n", "invalid YAML"),
        ("---\nid: a\nid: b\n---\nbody\n", "duplicate key 'id'"),
    ],
)
def test_malformed_content(library_root: Path, text: str, message: str) -> None:
    (library_root / "skills" / "bad.md").write_text(text, encoding="utf-8")
    with pytest.raises(ArtifactParseError, match=message) as info:
        GlobalLibrary.load(library_root)
    assert info.value.path == library_root / "skills" / "bad.md"


# --- validation ------------------------------------------------------------------------


def _replace(root: Path, artifact_type: str, old: str, new: str) -> None:
    path = write_artifact(root, "item", artifact_type)
    path.write_text(path.read_text().replace(old, new, 1))


@pytest.mark.parametrize("version", ["2", "0", "'1'", "true", "null"])
def test_unsupported_schema_version(library_root: Path, version: str) -> None:
    _replace(library_root, "skill", "version: 1", f"version: {version}")
    with pytest.raises(ArtifactValidationError, match="unsupported schema version"):
        GlobalLibrary.load(library_root)


def test_missing_version(library_root: Path) -> None:
    _replace(library_root, "skill", "version: 1\n", "")
    with pytest.raises(ArtifactValidationError, match="unsupported schema version None"):
        GlobalLibrary.load(library_root)


def test_invalid_type(library_root: Path) -> None:
    _replace(library_root, "skill", "type: skill", "type: agent")
    with pytest.raises(ArtifactValidationError, match="invalid type 'agent'"):
        GlobalLibrary.load(library_root)


def test_type_must_match_directory(library_root: Path) -> None:
    write_artifact(library_root, "secrets", "policy", directory="guidelines")
    with pytest.raises(ArtifactValidationError,
                       match="type 'policy' does not match its directory 'guidelines/'"):
        GlobalLibrary.load(library_root)


def test_missing_id(library_root: Path) -> None:
    _replace(library_root, "skill", "id: item\n", "")
    with pytest.raises(ArtifactValidationError, match="id: Field required"):
        GlobalLibrary.load(library_root)


@pytest.mark.parametrize("bad_id", ["Laravel", "../etc", "has space", "-lead", "a/b", "''"])
def test_malformed_id(library_root: Path, bad_id: str) -> None:
    _replace(library_root, "skill", "id: item", f"id: {bad_id}")
    with pytest.raises(ArtifactValidationError, match="id"):
        GlobalLibrary.load(library_root)


def test_duplicate_id_within_a_type(library_root: Path) -> None:
    write_artifact(library_root, "python", "skill", filename="a-python.md")
    write_artifact(library_root, "python", "skill", filename="b-python.md")
    expected = re.escape("duplicate skill id 'python' (already declared in skills/a-python.md)")
    with pytest.raises(ArtifactValidationError, match=expected) as info:
        GlobalLibrary.load(library_root)
    assert info.value.path == library_root.resolve() / "skills" / "b-python.md"


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("name: Item\n", "", "name"),
        ("description: About item.", "description: '   '", "description"),
        ("description: About item.", "description: [a, b]", "description"),
        ("---\nBody.", "tags: [ok, ok]\n---\nBody.", "tags"),
        ("---\nBody.", "tags: [Not-Slug]\n---\nBody.", "tags"),
        ("---\nBody.", "provider: openai\n---\nBody.", "provider"),
        ("---\nBody.", "model: gpt\n---\nBody.", "model"),
        ("---\nBody.", "role: implementer\n---\nBody.", "role"),
    ],
)
def test_malformed_metadata(library_root: Path, old: str, new: str, field: str) -> None:
    _replace(library_root, "skill", old, new)
    with pytest.raises(ArtifactValidationError, match=field):
        GlobalLibrary.load(library_root)


@pytest.mark.parametrize(
    ("applies_to", "message"),
    [
        ("  always: false", "declare 'always: true' or at least one"),
        ("  {}", "declare 'always: true' or at least one"),
        ("  always: true\n  stacks: [php]", "cannot be combined"),
        ("  stacks: [php, php]", "unique"),
        ("  stacks: [PHP]", "stacks"),
        ("  languages: [php]", "languages"),
    ],
)
def test_malformed_applies_to(library_root: Path, applies_to: str, message: str) -> None:
    write_artifact(library_root, "x", "skill", applies_to=applies_to)
    with pytest.raises(ArtifactValidationError, match=message):
        GlobalLibrary.load(library_root)


def test_missing_applies_to(library_root: Path) -> None:
    (library_root / "skills" / "x.md").write_text(
        "---\nversion: 1\nid: x\ntype: skill\nname: X\ndescription: d\n---\nBody.\n"
    )
    with pytest.raises(ArtifactValidationError, match="applies_to: Field required"):
        GlobalLibrary.load(library_root)


def test_empty_body(library_root: Path) -> None:
    write_artifact(library_root, "x", "skill", body="   \n")
    with pytest.raises(ArtifactValidationError, match="body is empty"):
        GlobalLibrary.load(library_root)


def test_only_specialties_may_reference(library_root: Path) -> None:
    write_artifact(library_root, "x", "skill", extra="skills: [x]\n")
    with pytest.raises(ArtifactValidationError, match="skills"):
        GlobalLibrary.load(library_root)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("skills: [ghost]\n", "references unknown skill 'ghost'"),
        ("rules: [ghost]\n", "references unknown rule 'ghost'"),
        # A reference is typed: a guideline id is not a rule.
        ("rules: [coding]\n", "references unknown rule 'coding'"),
    ],
)
def test_unknown_reference(library_root: Path, extra: str, message: str) -> None:
    write_artifact(library_root, "coding", "guideline")
    path = write_artifact(library_root, "domain", "specialty", extra=extra)
    with pytest.raises(ArtifactValidationError, match=message) as info:
        GlobalLibrary.load(library_root)
    assert info.value.path == path


def test_errors_are_reported_in_a_stable_order(library_root: Path) -> None:
    (library_root / "skills" / "b.md").write_text("broken")
    (library_root / "skills" / "a.md").write_text("broken")
    (library_root / "policies" / "z.md").write_text("broken")
    for _ in range(3):
        with pytest.raises(ArtifactParseError) as info:
            load_artifacts(library_root)
        assert info.value.path == library_root / "policies" / "z.md"


# --- root resolution / portability --------------------------------------------------------


def test_library_root_defaults_to_the_installation_directory() -> None:
    assert resolve_library_root(environ={}) == default_harness_root()


def test_library_root_precedence(library_root: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    env = {LIBRARY_ROOT_ENV: str(other)}
    assert resolve_library_root(library_root, env) == library_root.resolve()
    assert resolve_library_root(None, env) == other.resolve()


def test_library_root_ignores_harness_root_env(library_root: Path) -> None:
    env = {"HARNESS_ROOT": str(library_root)}
    assert resolve_library_root(environ=env) == default_harness_root()


def test_invalid_library_root(tmp_path: Path) -> None:
    with pytest.raises(LibraryStructureError, match=LIBRARY_ROOT_ENV):
        resolve_library_root(environ={LIBRARY_ROOT_ENV: str(tmp_path / "nope")})


def test_loading_does_not_depend_on_cwd(
    library_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_artifact(library_root, "python", "skill", applies_to="  stacks: [python]")
    expected = [a.summary() for a in GlobalLibrary.load(library_root).artifacts()]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert [a.summary() for a in GlobalLibrary.load(library_root).artifacts()] == expected
    assert resolve_library_root(environ={}) == default_harness_root()


def test_relative_root_is_resolved(library_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(library_root.parent)
    library = GlobalLibrary.load(Path(library_root.name))
    assert library.root == library_root.resolve()


def test_summary_is_json_ready_and_omits_body(library_root: Path) -> None:
    write_artifact(library_root, "domain", "specialty", extra="rules: []\n")
    summary = GlobalLibrary.load(library_root).get(ArtifactType.SPECIALTY, "domain").summary()
    assert summary["key"] == "specialty/domain"
    assert summary["authority"] == Authority.KNOWLEDGE
    assert summary["source"] == "specialties/domain.md"
    assert summary["skills"] == [] and summary["rules"] == []
    assert "body" not in summary

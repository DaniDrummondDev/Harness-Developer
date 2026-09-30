"""V1 Global Library: deterministic resolution, semantics and the shipped content."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from library_helpers import write_artifact
from pydantic import ValidationError

from orchestrator.config import default_harness_root, load_config
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.models import (
    AUTHORITY_BY_TYPE,
    PRECEDENCE,
    Artifact,
    ArtifactType,
    Authority,
    ProjectProfile,
)
from orchestrator.memory.safety import Verdict, evaluate


def keys(matches: tuple[object, ...]) -> list[str]:
    return [m.artifact.key for m in matches]  # type: ignore[attr-defined]


@pytest.fixture
def library(library_root: Path) -> GlobalLibrary:
    write_artifact(library_root, "secrets", "policy")
    write_artifact(library_root, "coding", "guideline")
    write_artifact(library_root, "thin-controllers", "rule",
                   applies_to="  stacks: [laravel]\n  capabilities: [api]")
    write_artifact(library_root, "laravel", "skill", applies_to="  stacks: [laravel]")
    write_artifact(library_root, "python", "skill", applies_to="  stacks: [python]")
    write_artifact(library_root, "database", "skill",
                   applies_to="  stacks: [mysql, postgresql]\n  capabilities: [database]")
    write_artifact(library_root, "php-laravel", "specialty", applies_to="  stacks: [laravel]",
                   extra="skills: [laravel]\nrules: [thin-controllers]\n")
    return GlobalLibrary.load(library_root)


def test_known_stack_selects_expected_items(library: GlobalLibrary) -> None:
    matches = library.resolve(ProjectProfile(stack=("laravel",)))
    assert keys(matches) == [
        "policy/secrets", "guideline/coding", "rule/thin-controllers",
        "skill/laravel", "specialty/php-laravel",
    ]
    reasons = {m.artifact.key: m.reasons for m in matches}
    assert reasons["policy/secrets"] == ("always",)
    assert reasons["skill/laravel"] == ("stack:laravel",)


def test_unknown_stack_yields_no_false_positive(library: GlobalLibrary) -> None:
    matches = library.resolve(ProjectProfile(stack=("cobol",), capabilities=("mainframe",)))
    assert keys(matches) == ["policy/secrets", "guideline/coding"]
    assert all(m.reasons == ("always",) for m in matches)


def test_empty_profile_gets_only_universal_items(library: GlobalLibrary) -> None:
    assert keys(library.resolve(ProjectProfile())) == ["policy/secrets", "guideline/coding"]


def test_partial_names_do_not_match(library: GlobalLibrary) -> None:
    # Exact matching only: no prefixes, substrings or aliases.
    for stack in ("lara", "laravel-11", "php", "py", "mysql8"):
        matches = library.resolve(ProjectProfile(stack=(stack,)))
        assert keys(matches) == ["policy/secrets", "guideline/coding"], stack


def test_multiple_stacks_and_capabilities(library: GlobalLibrary) -> None:
    profile = ProjectProfile(stack=("python", "postgresql"), capabilities=("api",))
    matches = library.resolve(profile)
    assert keys(matches) == [
        "policy/secrets", "guideline/coding", "rule/thin-controllers",
        "skill/database", "skill/python",
    ]
    reasons = {m.artifact.key: m.reasons for m in matches}
    assert reasons["rule/thin-controllers"] == ("capability:api",)
    assert reasons["skill/database"] == ("stack:postgresql",)


def test_every_matching_reason_is_reported(library: GlobalLibrary) -> None:
    profile = ProjectProfile(stack=("laravel", "mysql"), capabilities=("api", "database"))
    reasons = {m.artifact.key: m.reasons for m in library.resolve(profile)}
    assert reasons["rule/thin-controllers"] == ("stack:laravel", "capability:api")
    assert reasons["skill/database"] == ("stack:mysql", "capability:database")


def test_resolution_is_deterministic_regardless_of_declaration_order(
    library: GlobalLibrary,
) -> None:
    stack = ("laravel", "mysql", "python", "docker")
    expected = library.resolve(ProjectProfile(stack=stack))
    for order in itertools.permutations(stack):
        assert library.resolve(ProjectProfile(stack=(*order, order[0]))) == expected


def test_profile_is_normalized_and_validated() -> None:
    profile = ProjectProfile(stack=("php", "laravel", "php"), capabilities=("api",))
    assert profile.stack == ("laravel", "php")
    with pytest.raises(ValidationError):
        ProjectProfile(stack=("Laravel",))
    with pytest.raises(ValidationError):
        ProjectProfile(stack=("../x",))


# --- semantics: policy vs guideline vs knowledge ---------------------------------------------


def test_types_have_fixed_distinct_authority() -> None:
    assert AUTHORITY_BY_TYPE[ArtifactType.POLICY] is Authority.MANDATORY
    assert AUTHORITY_BY_TYPE[ArtifactType.GUIDELINE] is Authority.RECOMMENDED
    assert AUTHORITY_BY_TYPE[ArtifactType.RULE] is Authority.RECOMMENDED
    assert AUTHORITY_BY_TYPE[ArtifactType.SKILL] is Authority.KNOWLEDGE
    assert AUTHORITY_BY_TYPE[ArtifactType.SPECIALTY] is Authority.KNOWLEDGE
    assert set(AUTHORITY_BY_TYPE) == set(ArtifactType)


def test_policies_outrank_guidelines_which_outrank_knowledge() -> None:
    # docs/03 §17: Policies > ... > guidelines > skills/specialties.
    assert (PRECEDENCE[Authority.MANDATORY] < PRECEDENCE[Authority.RECOMMENDED]
            < PRECEDENCE[Authority.KNOWLEDGE])


def test_policy_and_guideline_with_same_id_stay_distinct(library_root: Path) -> None:
    write_artifact(library_root, "security", "guideline")
    write_artifact(library_root, "security", "policy")
    library = GlobalLibrary.load(library_root)
    policy = library.get(ArtifactType.POLICY, "security")
    guideline = library.get(ArtifactType.GUIDELINE, "security")
    assert policy.authority is Authority.MANDATORY
    assert guideline.authority is Authority.RECOMMENDED
    assert keys(library.resolve(ProjectProfile())) == ["policy/security", "guideline/security"]


def test_resolved_order_follows_precedence(library: GlobalLibrary) -> None:
    profile = ProjectProfile(stack=("laravel", "python", "mysql"), capabilities=("api",))
    ranks = [PRECEDENCE[m.artifact.authority] for m in library.resolve(profile)]
    assert ranks == sorted(ranks)


# --- shipped library (engineering/{policies,guidelines,rules,skills,specialties}) -------------


@pytest.fixture(scope="module")
def shipped() -> GlobalLibrary:
    return GlobalLibrary.load(default_harness_root())


def test_shipped_library_is_valid_and_covers_the_roadmap(shipped: GlobalLibrary) -> None:
    ids = {t: {a.id for a in shipped.by_type(t)} for t in ArtifactType}
    assert {"python", "laravel", "testing", "database", "security", "api",
            "docker"} <= ids[ArtifactType.SKILL]
    assert {"coding", "architecture", "testing", "documentation",
            "review"} <= ids[ArtifactType.GUIDELINE]
    assert {"secrets", "security", "git", "breaking-changes", "deploy"} <= ids[ArtifactType.POLICY]
    assert {"thin-controllers", "explicit-authorization", "validation-at-boundaries",
            "avoid-unnecessary-abstractions"} <= ids[ArtifactType.RULE]
    assert {"architecture", "python", "php-laravel", "testing", "database",
            "security"} <= ids[ArtifactType.SPECIALTY]


def test_shipped_policies_apply_to_every_project(shipped: GlobalLibrary) -> None:
    # Fail closed: a policy must not depend on the project remembering a capability.
    assert all(p.metadata.applies_to.always for p in shipped.by_type(ArtifactType.POLICY))


def test_laravel_project_inherits_global_knowledge(shipped: GlobalLibrary) -> None:
    profile = ProjectProfile(stack=("php", "laravel", "mysql", "redis", "docker"),
                             capabilities=("api",))
    resolved = set(keys(shipped.resolve(profile)))
    assert {
        "skill/laravel", "skill/database", "skill/docker", "skill/api", "skill/testing",
        "skill/security", "specialty/php-laravel", "specialty/database",
        "rule/thin-controllers", "rule/explicit-authorization",
        "policy/secrets", "policy/security", "guideline/testing",
    } <= resolved
    assert "skill/python" not in resolved
    assert "specialty/python" not in resolved


def test_this_project_profile_resolves(shipped: GlobalLibrary) -> None:
    project = load_config(default_harness_root()).project
    profile = ProjectProfile(stack=tuple(project.stack), capabilities=tuple(project.capabilities))
    resolved = set(keys(shipped.resolve(profile)))
    assert {"skill/python", "specialty/python", "policy/secrets"} <= resolved
    assert "skill/laravel" not in resolved


def test_shipped_artifacts_contain_no_secrets(shipped: GlobalLibrary) -> None:
    for artifact in shipped.artifacts():
        verdict = evaluate(_full_text(artifact))
        assert verdict.verdict is Verdict.ALLOW, (artifact.key, verdict.rules)


def _full_text(artifact: Artifact) -> str:
    return (default_harness_root() / artifact.source).read_text(encoding="utf-8")

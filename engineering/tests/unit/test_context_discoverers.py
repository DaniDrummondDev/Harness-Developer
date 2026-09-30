"""V1.1 context discovery: each discoverer in isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from library_helpers import write_artifact

from orchestrator.context.discoverers import (
    AdrDiscoverer,
    DocumentationDiscoverer,
    InstructionsDiscoverer,
    LibraryDiscoverer,
    MemoryDiscoverer,
    RepositoryHintsDiscoverer,
    UnconsultedSource,
    extract_hints,
)
from orchestrator.context.files import ProjectFiles
from orchestrator.context.models import (
    CandidateKind,
    ReferenceMatch,
    ReferenceStore,
    SourceStatus,
)
from orchestrator.core.exceptions import ContextDiscoveryError
from orchestrator.core.request import EngineeringRequest
from orchestrator.intake import normalize_request
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.models import ProjectProfile
from orchestrator.memory.fake import FakeMemoryProvider
from orchestrator.memory.models import MemoryScope, ScopeKind
from orchestrator.memory.service import MemoryService


def request(text: str = "do something", ref: str | None = None) -> EngineeringRequest:
    return normalize_request(source="cli", instruction=text, origin_ref=ref)


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    touch(root / "CLAUDE.md", "# Agent rules\n")
    touch(root / "README.md", "# Shop\n")
    touch(root / "docs" / "architecture.md", "# Architecture\n")
    touch(root / "docs" / "guide.rst", "Guide\n")
    touch(root / "docs" / "diagram.png", "png")
    touch(root / "docs" / "adr" / "README.md", "# ADR index\n")
    touch(root / "docs" / "adr" / "0002-queue.md", "# ADR-0002: Queue\n\n- Status: Accepted\n")
    touch(root / "docs" / "adr" / "0001-money.md",
          "# ADR-0001: Money\n\n- Status: Superseded by ADR-0003\n")
    touch(root / "app" / "Http" / "OrderController.php", "<?php")
    touch(root / "app" / "Models" / "Order.php", "<?php")
    touch(root / "src" / "billing" / "invoice.py", "pass")
    touch(root / "src" / "billing" / "tax.py", "pass")
    touch(root / "src" / "other" / "invoice.py", "pass")
    touch(root / "vendor" / "lib" / "Order.php", "<?php")
    touch(root / ".env", "APP_KEY=abc")
    touch(root / "config" / "secrets.yaml", "k: v")
    return root


@pytest.fixture
def files(project: Path) -> ProjectFiles:
    return ProjectFiles(project, max_files=1000, max_file_bytes=100_000)


def ids(found: object) -> list[str]:
    return [c.id for c in found.candidates]  # type: ignore[attr-defined]


# --- library ---------------------------------------------------------------------------------


@pytest.fixture
def library(library_root: Path) -> GlobalLibrary:
    write_artifact(library_root, "secrets", "policy")
    write_artifact(library_root, "coding", "guideline")
    write_artifact(library_root, "thin-controllers", "rule", applies_to="  stacks: [laravel]")
    write_artifact(library_root, "laravel", "skill", applies_to="  stacks: [laravel]")
    write_artifact(library_root, "python", "skill", applies_to="  stacks: [python]")
    write_artifact(library_root, "php-laravel", "specialty", applies_to="  stacks: [laravel]",
                   extra="skills: [laravel]\n")
    return GlobalLibrary.load(library_root)


def test_library_candidates_follow_the_profile(library: GlobalLibrary) -> None:
    found = LibraryDiscoverer(library, ProjectProfile(stack=("laravel",))).discover(request())
    assert ids(found) == [
        "policy/secrets", "guideline/coding", "rule/thin-controllers", "skill/laravel",
        "specialty/php-laravel",
    ]
    kinds = [c.kind for c in found.candidates]
    assert kinds == [CandidateKind.POLICY, CandidateKind.GUIDELINE, CandidateKind.RULE,
                     CandidateKind.SKILL, CandidateKind.SPECIALTY]
    policy = found.candidates[0]
    assert policy.metadata["authority"] == "mandatory"
    assert policy.metadata["applies"] == ("always",)
    assert policy.reference.store is ReferenceStore.LIBRARY
    assert policy.reference.path == "policies/secrets.md"
    assert "applies to the project profile: always" in policy.provenance[0].reason
    assert found.candidates[1].metadata["authority"] == "recommended"


def test_library_candidates_reuse_resolution_not_the_request_text(library: GlobalLibrary) -> None:
    profile = ProjectProfile(stack=("python",))
    first = LibraryDiscoverer(library, profile).discover(request("laravel controller work"))
    second = LibraryDiscoverer(library, profile).discover(request("anything else"))
    assert ids(first) == ids(second) == ["policy/secrets", "guideline/coding", "skill/python"]
    assert [m.artifact.key for m in library.resolve(profile)] == ids(first)


# --- instructions / documentation / ADRs -------------------------------------------------------


def test_instructions_only_existing_files(files: ProjectFiles) -> None:
    found = InstructionsDiscoverer(files, ["CLAUDE.md", "AGENTS.md"]).discover(request())
    assert ids(found) == ["instructions/CLAUDE.md"]
    assert found.candidates[0].title == "Agent rules"
    assert found.warnings == ("'AGENTS.md' does not exist",)


def test_instructions_never_expose_secret_files(files: ProjectFiles) -> None:
    found = InstructionsDiscoverer(files, [".env"]).discover(request())
    assert found.candidates == ()
    assert found.warnings == ("skipped '.env': looks like a secret file",)


def test_documentation_roots_and_files(files: ProjectFiles) -> None:
    found = DocumentationDiscoverer(files, ["README.md", "docs"]).discover(request())
    # Configured order, then a sorted depth-first walk (files before subdirectories);
    # the discovery service sorts the merged result globally.
    assert ids(found) == [
        "doc/README.md", "doc/docs/architecture.md", "doc/docs/guide.rst",
        "doc/docs/adr/0001-money.md", "doc/docs/adr/0002-queue.md", "doc/docs/adr/README.md",
    ]
    by_id = {c.id: c for c in found.candidates}
    assert by_id["doc/docs/architecture.md"].title == "Architecture"
    assert by_id["doc/docs/guide.rst"].title == "guide.rst"
    assert by_id["doc/README.md"].metadata["size_bytes"] == len("# Shop\n")
    assert found.warnings == ()


def test_missing_optional_root_is_a_warning(files: ProjectFiles) -> None:
    found = DocumentationDiscoverer(files, ["handbook"]).discover(request())
    assert found.candidates == () and found.status is SourceStatus.OK
    assert found.warnings == ("'handbook' does not exist",)


def test_configured_root_escaping_the_project_is_fatal(files: ProjectFiles, project: Path,
                                                       tmp_path: Path) -> None:
    (tmp_path / "elsewhere").mkdir()
    (project / "linked-docs").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    with pytest.raises(ContextDiscoveryError, match="outside the project root"):
        DocumentationDiscoverer(files, ["linked-docs"]).discover(request())


def test_adrs_with_status_and_number(files: ProjectFiles) -> None:
    found = AdrDiscoverer(files, ["docs/adr"]).discover(request())
    assert ids(found) == ["adr/docs/adr/0001-money.md", "adr/docs/adr/0002-queue.md"]
    first, second = found.candidates
    assert first.title == "ADR-0001: Money"
    assert first.metadata["status"] == "Superseded by ADR-0003"
    assert first.metadata["number"] == "0001"
    assert second.metadata["status"] == "Accepted"
    assert all(c.kind is CandidateKind.ADR for c in found.candidates)


def test_adr_root_absent_is_a_warning(files: ProjectFiles) -> None:
    found = AdrDiscoverer(files, ["docs/decisions"]).discover(request())
    assert found.candidates == ()
    assert found.warnings == ("'docs/decisions' does not exist",)


# --- repository hints --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("fix `src/billing/invoice.py:42`, then tax.py.", ("src/billing/invoice.py", "tax.py")),
        ("see https://example.com/a/b.py and docs/", ("docs/",)),
        ("update Order.php (and Order.php again)", ("Order.php",)),
        ("nothing here", ()),
        ("version 1.2 of e.g. things", ()),
        (r"windows app\Models\Order.php", ("app/Models/Order.php",)),
    ],
)
def test_extract_hints(text: str, expected: tuple[str, ...]) -> None:
    assert extract_hints(text) == expected


def test_explicit_path_becomes_candidate(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["."]).discover(
        request("refactor app/Http/OrderController.php")
    )
    assert ids(found) == ["source/app/Http/OrderController.php"]
    candidate = found.candidates[0]
    assert candidate.kind is CandidateKind.SOURCE_CODE
    assert candidate.provenance[0].reason == (
        "named in the request: 'app/Http/OrderController.php'"
    )
    assert candidate.provenance[0].match is ReferenceMatch.PATH
    assert found.warnings == ()


def test_path_relative_to_a_source_root(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["src"]).discover(request("edit billing/tax.py"))
    assert ids(found) == ["source/src/billing/tax.py"]
    assert found.candidates[0].provenance[0].match is ReferenceMatch.PATH


def test_file_name_matches_every_file_with_that_name(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["src", "app"]).discover(request("fix invoice.py"))
    assert ids(found) == ["source/src/billing/invoice.py", "source/src/other/invoice.py"]
    assert {c.provenance[0].match for c in found.candidates} == {
        ReferenceMatch.AMBIGUOUS_FILE_NAME
    }


def test_unique_file_name_is_an_exact_match(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["src"]).discover(request("fix tax.py"))
    assert ids(found) == ["source/src/billing/tax.py"]
    assert found.candidates[0].provenance[0].match is ReferenceMatch.FILE_NAME


def test_directory_hint_lists_its_direct_files(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["."]).discover(request("look at src/billing/"))
    assert ids(found) == ["source/src/billing/invoice.py", "source/src/billing/tax.py"]
    assert {c.provenance[0].match for c in found.candidates} == {ReferenceMatch.DIRECTORY}


def test_only_repository_hints_set_a_match(files: ProjectFiles) -> None:
    found = DocumentationDiscoverer(files, ["docs"]).discover(request())
    assert found.candidates and all(c.provenance[0].match is None for c in found.candidates)


def test_origin_ref_is_a_hint_source(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["."]).discover(
        request("do the task", ref="docs/architecture.md")
    )
    assert ids(found) == ["source/docs/architecture.md"]
    assert found.candidates[0].provenance[0].reason.startswith("named in the origin_ref")


def test_missing_path_does_not_break_discovery(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["."]).discover(
        request("fix app/Missing.php and app/Models/Order.php")
    )
    assert ids(found) == ["source/app/Models/Order.php"]
    assert found.warnings == ("hint 'app/Missing.php' not found in the project",)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("read ../../etc/passwd", "resolves outside the project root"),
        ("read /etc/passwd", "resolves outside the project root"),
        ("read vendor/lib/Order.php", "inside an excluded directory"),
        ("read config/secrets.yaml", "looks like a secret file"),
    ],
)
def test_unsafe_hints_are_rejected(files: ProjectFiles, text: str, reason: str) -> None:
    found = RepositoryHintsDiscoverer(files, ["."]).discover(request(text))
    assert found.candidates == ()
    assert found.warnings[0].endswith(reason)


def test_symlink_hint_escaping_the_project_is_rejected(files: ProjectFiles, project: Path,
                                                       tmp_path: Path) -> None:
    touch(tmp_path / "secret.txt")
    (project / "src" / "link.txt").symlink_to(tmp_path / "secret.txt")
    found = RepositoryHintsDiscoverer(files, ["."]).discover(request("see src/link.txt"))
    assert found.candidates == ()
    assert "resolves outside the project root" in found.warnings[0]


def test_file_names_never_match_excluded_or_secret_files(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["."]).discover(request("check Order.php and .env"))
    assert ids(found) == ["source/app/Models/Order.php"]  # not vendor/lib/Order.php


def test_request_without_hints(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["."]).discover(request("improve performance"))
    assert found.candidates == ()
    assert found.warnings == ("the request names no file or path",)


def test_no_hint_matched(files: ProjectFiles) -> None:
    found = RepositoryHintsDiscoverer(files, ["."]).discover(request("fix nothing.py"))
    assert found.warnings == ("no repository file matched the request's hints",)


# --- memory ------------------------------------------------------------------------------------


@pytest.fixture
def memory() -> MemoryService:
    service = MemoryService(FakeMemoryProvider(), project="shop")
    project = service.scope("project")
    service.add("Invoices are rounded half-even", scope=project,
                source=service.source("decision:D-7"))
    service.add("Deploys run on Tuesdays", scope=project, source=service.source("release:v1"))
    service.add("Invoice task note", scope=service.scope("task:T-1"),
                source=service.source("task_result:T-1"))
    return service


def test_memory_hits_become_candidates(memory: MemoryService) -> None:
    found = MemoryDiscoverer(memory, limit=5).discover(request("how are invoices rounded"))
    assert ids(found) == ["memory/fake-000001"]
    candidate = found.candidates[0]
    assert candidate.kind is CandidateKind.MEMORY
    assert candidate.reference.store is ReferenceStore.MEMORY
    assert candidate.metadata["lineage"] == "decision:D-7"
    assert candidate.metadata["scope"] == "project"
    assert candidate.metadata["search_rank"] == 1
    assert candidate.metadata["source_of_truth"] is False
    assert candidate.metadata["excerpt"] == "Invoices are rounded half-even"


def test_memory_searches_only_the_project_scope(memory: MemoryService) -> None:
    found = MemoryDiscoverer(memory, limit=5).discover(request("invoice task note"))
    assert "memory/fake-000003" not in ids(found)


def test_zero_memory_hits_is_valid(memory: MemoryService) -> None:
    found = MemoryDiscoverer(memory, limit=5).discover(request("kubernetes autoscaling"))
    assert found.candidates == () and found.status is SourceStatus.OK
    assert found.warnings == ("no memory matched the request",)


def test_memory_failure_is_a_warning_not_an_error() -> None:
    service = MemoryService(FakeMemoryProvider(unavailable=True), project="shop")
    found = MemoryDiscoverer(service, limit=5).discover(request("anything"))
    assert found.status is SourceStatus.UNAVAILABLE
    assert found.candidates == ()
    assert "search failed" in found.warnings[0] and "unavailable" in found.warnings[0]


def test_memory_invalid_query_is_a_warning() -> None:
    service = MemoryService(FakeMemoryProvider(), project="shop")
    found = MemoryDiscoverer(service, limit=5).discover(request("x" * 9000))
    assert found.status is SourceStatus.UNAVAILABLE


def test_memory_discovery_never_writes() -> None:
    provider = FakeMemoryProvider()
    service = MemoryService(provider, project="shop")
    MemoryDiscoverer(service, limit=5).discover(request("anything at all"))
    scope = MemoryScope(project="shop", kind=ScopeKind.PROJECT)
    assert service.search("anything", scope=scope) == ()
    assert provider.health().detail == "in-process, 0 memories"


def test_unconsulted_source_reports_without_candidates() -> None:
    found = UnconsultedSource("memory", SourceStatus.SKIPPED, "memory is disabled").discover(
        request()
    )
    assert found.candidates == ()
    assert found.status is SourceStatus.SKIPPED
    assert found.warnings == ("memory is disabled",)

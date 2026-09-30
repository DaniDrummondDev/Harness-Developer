"""V1.1 context discovery: aggregation, deduplication, composition, config, doctor, CLI."""

from __future__ import annotations

import ast
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from library_helpers import write_artifact
from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.config import load_config
from orchestrator.context.discoverers import Discovered
from orchestrator.context.discovery import (
    ContextCandidateDiscovery,
    build_discovery,
    check_discovery_paths,
)
from orchestrator.context.files import ProjectFiles
from orchestrator.context.models import (
    MERGE_CONFLICTS_KEY,
    CandidateKind,
    CandidateReference,
    ContextCandidate,
    Provenance,
    ReferenceMatch,
    ReferenceStore,
    SourceStatus,
)
from orchestrator.core.exceptions import ConfigValidationError, ContextDiscoveryError
from orchestrator.core.request import EngineeringRequest
from orchestrator.doctor import CheckStatus, check_context, run_doctor
from orchestrator.intake import normalize_request
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.loader import LIBRARY_ROOT_ENV
from orchestrator.memory.fake import FakeMemoryProvider
from orchestrator.memory.service import MemoryService
from orchestrator.utils.shell import CommandResult

WriteConfig = Callable[[str, str], Path]
runner = CliRunner()
PACKAGE = Path(__file__).resolve().parents[2] / "orchestrator"


def request(text: str = "do something", ref: str | None = None) -> EngineeringRequest:
    return normalize_request(source="cli", instruction=text, origin_ref=ref)


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def keys(result: object) -> list[str]:
    return [c.id for c in result.candidates]  # type: ignore[attr-defined]


class StaticDiscoverer:
    def __init__(self, name: str, *candidates: ContextCandidate) -> None:
        self.name = name
        self._candidates = candidates

    def discover(self, request: EngineeringRequest) -> Discovered:
        return Discovered(self._candidates)


def file_candidate(kind: CandidateKind, path: str, discoverer: str) -> ContextCandidate:
    return ContextCandidate(
        id=f"{kind}/{path}", kind=kind, title=path,
        reference=CandidateReference(store=ReferenceStore.PROJECT, path=path),
        provenance=(Provenance(discoverer=discoverer, reason=f"via {discoverer}"),),
    )


# --- aggregation -------------------------------------------------------------------------------


def test_same_file_from_two_discoverers_is_one_candidate_with_two_provenances(
    tmp_path: Path,
) -> None:
    touch(tmp_path / "docs" / "adr" / "0001.md")
    as_doc = file_candidate(CandidateKind.DOCUMENTATION, "docs/adr/0001.md", "documentation")
    as_adr = file_candidate(CandidateKind.ADR, "docs/adr/0001.md", "adrs")
    discovery = ContextCandidateDiscovery(
        [StaticDiscoverer("documentation", as_doc), StaticDiscoverer("adrs", as_adr)],
        roots={ReferenceStore.PROJECT: tmp_path},
    )
    result = discovery.discover(request())
    assert keys(result) == ["adr/docs/adr/0001.md"]  # the more specific kind wins
    assert [p.discoverer for p in result.candidates[0].provenance] == ["adrs", "documentation"]
    assert [(s.discoverer, s.candidates) for s in result.sources] == [
        ("documentation", 1), ("adrs", 1),
    ]


def test_dedup_uses_the_canonical_file_not_the_title_or_store(tmp_path: Path) -> None:
    # The Harness installation can live inside the project: the same file is a
    # library artifact and a repository file.
    library_root = tmp_path / "engineering"
    touch(library_root / "policies" / "secrets.md")
    library_candidate = ContextCandidate(
        id="policy/secrets", kind=CandidateKind.POLICY, title="Secrets handling",
        reference=CandidateReference(store=ReferenceStore.LIBRARY, path="policies/secrets.md"),
        provenance=(Provenance(discoverer="library", reason="always"),),
    )
    hinted = file_candidate(CandidateKind.SOURCE_CODE, "engineering/policies/secrets.md",
                            "repository_hints")
    same_title_other_file = file_candidate(
        CandidateKind.SOURCE_CODE, "notes.md", "repository_hints"
    ).model_copy(update={"title": "Secrets handling"})
    touch(tmp_path / "notes.md")
    discovery = ContextCandidateDiscovery(
        [StaticDiscoverer("library", library_candidate),
         StaticDiscoverer("repository_hints", hinted, same_title_other_file)],
        roots={ReferenceStore.PROJECT: tmp_path, ReferenceStore.LIBRARY: library_root},
    )
    result = discovery.discover(request())
    assert keys(result) == ["policy/secrets", "source/notes.md"]
    assert [p.discoverer for p in result.candidates[0].provenance] == [
        "library", "repository_hints",
    ]


def test_duplicate_from_the_same_discoverer_keeps_one_provenance(tmp_path: Path) -> None:
    touch(tmp_path / "a.py")
    candidate = file_candidate(CandidateKind.SOURCE_CODE, "a.py", "repository_hints")
    result = ContextCandidateDiscovery(
        [StaticDiscoverer("repository_hints", candidate, candidate)],
        roots={ReferenceStore.PROJECT: tmp_path},
    ).discover(request())
    assert keys(result) == ["source/a.py"]
    assert len(result.candidates[0].provenance) == 1


# --- V1.1 debt (fixed in V1.2): metadata of the losing duplicate ---------------------------------


def test_merge_keeps_metadata_of_every_duplicate(tmp_path: Path) -> None:
    touch(tmp_path / "docs" / "adr" / "0001.md")
    as_doc = file_candidate(CandidateKind.DOCUMENTATION, "docs/adr/0001.md", "documentation")
    as_doc = as_doc.model_copy(update={"metadata": {"size_bytes": 9, "owner": "docs-team"}})
    as_adr = file_candidate(CandidateKind.ADR, "docs/adr/0001.md", "adrs").model_copy(
        update={"metadata": {"size_bytes": 9, "status": "Superseded by ADR-0003"}}
    )
    hinted = file_candidate(CandidateKind.SOURCE_CODE, "docs/adr/0001.md", "repository_hints")
    hinted = hinted.model_copy(update={"provenance": (Provenance(
        discoverer="repository_hints", reason="named in the request: 'docs/adr/0001.md'",
        match=ReferenceMatch.PATH),)})
    result = ContextCandidateDiscovery(
        [StaticDiscoverer("documentation", as_doc), StaticDiscoverer("adrs", as_adr),
         StaticDiscoverer("repository_hints", hinted)],
        roots={ReferenceStore.PROJECT: tmp_path},
    ).discover(request())
    (merged,) = result.candidates
    assert merged.kind is CandidateKind.ADR
    assert merged.metadata == {
        "size_bytes": 9, "status": "Superseded by ADR-0003", "owner": "docs-team",
    }
    assert [(p.discoverer, p.match) for p in merged.provenance] == [
        ("adrs", None), ("documentation", None), ("repository_hints", ReferenceMatch.PATH),
    ]


def test_merge_records_contradictory_metadata_instead_of_dropping_it(tmp_path: Path) -> None:
    touch(tmp_path / "docs" / "adr" / "0001.md")
    as_doc = file_candidate(CandidateKind.DOCUMENTATION, "docs/adr/0001.md", "documentation")
    as_doc = as_doc.model_copy(update={"metadata": {"status": "Accepted"}})
    as_adr = file_candidate(CandidateKind.ADR, "docs/adr/0001.md", "adrs").model_copy(
        update={"metadata": {"status": "Deprecated"}}
    )
    result = ContextCandidateDiscovery(
        [StaticDiscoverer("documentation", as_doc), StaticDiscoverer("adrs", as_adr)],
        roots={ReferenceStore.PROJECT: tmp_path},
    ).discover(request())
    metadata = result.candidates[0].metadata
    assert metadata["status"] == "Deprecated"  # the winning (more specific) kind's value
    assert metadata[MERGE_CONFLICTS_KEY] == (
        "status: kept 'Deprecated' (adr), dropped 'Accepted' (doc via documentation)",
    )


def test_output_is_sorted_by_kind_then_id(tmp_path: Path) -> None:
    candidates = [
        file_candidate(CandidateKind.SOURCE_CODE, "b.py", "x"),
        file_candidate(CandidateKind.DOCUMENTATION, "z.md", "x"),
        file_candidate(CandidateKind.SOURCE_CODE, "a.py", "x"),
        file_candidate(CandidateKind.ADR, "adr.md", "x"),
    ]
    result = ContextCandidateDiscovery(
        [StaticDiscoverer("x", *candidates)], roots={ReferenceStore.PROJECT: tmp_path}
    ).discover(request())
    assert keys(result) == ["adr/adr.md", "doc/z.md", "source/a.py", "source/b.py"]


def test_discoverer_names_must_be_unique(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unique"):
        ContextCandidateDiscovery([StaticDiscoverer("x"), StaticDiscoverer("x")], roots={})


# --- composition from configuration -------------------------------------------------------------


@pytest.fixture
def library(library_root: Path) -> GlobalLibrary:
    write_artifact(library_root, "secrets", "policy")
    write_artifact(library_root, "python", "skill", applies_to="  stacks: [python]")
    write_artifact(library_root, "laravel", "skill", applies_to="  stacks: [laravel]")
    return GlobalLibrary.load(library_root)


@pytest.fixture
def project(harness_root: Path, write_config: WriteConfig) -> Path:
    """harness_root's project root is its parent (tmp_path): populate it."""
    root = harness_root.parent
    touch(root / "AGENTS.md", "# Agents\n")
    touch(root / "docs" / "overview.md", "# Overview\n")
    touch(root / "docs" / "adr" / "0001-cents.md", "# ADR-0001: Cents\n- Status: Accepted\n")
    touch(root / "src" / "billing" / "invoice.py")
    write_config("context.yaml", """
        version: 1
        context:
          enabled: true
          discovery:
            instruction_files: [AGENTS.md, CLAUDE.md]
            documentation_paths: [docs]
            adr_paths: [docs/adr]
            source_roots: [src]
            exclude_dirs: [harness]
    """)
    return root


def test_end_to_end_discovery_from_config(harness_root: Path, project: Path,
                                          library: GlobalLibrary) -> None:
    config = load_config(harness_root)
    result = build_discovery(config, library).discover(
        request("fix rounding in billing/invoice.py per docs/adr/0001-cents.md")
    )
    assert keys(result) == [
        "policy/secrets", "skill/python", "instructions/AGENTS.md",
        "adr/docs/adr/0001-cents.md", "doc/docs/overview.md", "source/src/billing/invoice.py",
    ]
    adr = result.candidates[3]
    assert {p.discoverer for p in adr.provenance} == {"adrs", "documentation", "repository_hints"}
    assert [(s.discoverer, s.status, s.candidates) for s in result.sources] == [
        ("library", SourceStatus.OK, 2), ("instructions", SourceStatus.OK, 1),
        ("adrs", SourceStatus.OK, 1), ("documentation", SourceStatus.OK, 2),
        ("repository_hints", SourceStatus.OK, 2), ("memory", SourceStatus.SKIPPED, 0),
    ]
    assert result.warnings == (
        "instructions: 'CLAUDE.md' does not exist", "memory: memory is disabled in memory.yaml",
    )
    assert result.request.instruction.startswith("fix rounding")
    assert all("classification" not in c.model_dump() for c in result.candidates)


def test_discovery_is_deterministic(harness_root: Path, project: Path,
                                    library: GlobalLibrary) -> None:
    config = load_config(harness_root)
    req = request("see docs/ and invoice.py")
    first = build_discovery(config, library).discover(req)
    second = build_discovery(config, library).discover(req)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_discovery_does_not_depend_on_cwd(harness_root: Path, project: Path,
                                          library: GlobalLibrary, tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    req = request("see docs/overview.md")
    expected = build_discovery(load_config(harness_root), library).discover(req)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert build_discovery(load_config(harness_root), library).discover(req) == expected


def test_disabled_context_is_fatal(harness_root: Path, write_config: WriteConfig,
                                   library: GlobalLibrary) -> None:
    write_config("context.yaml", "version: 1\ncontext: {enabled: false}\n")
    with pytest.raises(ContextDiscoveryError, match="disabled"):
        build_discovery(load_config(harness_root), library)


def test_configured_path_escaping_via_symlink_is_fatal(harness_root: Path, project: Path,
                                                       library: GlobalLibrary,
                                                       tmp_path_factory: pytest.TempPathFactory,
                                                       ) -> None:
    outside = tmp_path_factory.mktemp("outside")
    (project / "docs" / "adr").rename(project / "old-adr")
    (project / "docs" / "adr").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ContextDiscoveryError, match="outside the project root"):
        build_discovery(load_config(harness_root), library)


def _enable_memory(write_config: WriteConfig) -> None:
    write_config("memory.yaml", """
        version: 1
        memory:
          enabled: true
          backend: mem0
          mem0: {base_url: "http://localhost:1"}
    """)


def test_memory_enabled_with_searcher(harness_root: Path, project: Path, write_config: WriteConfig,
                                      library: GlobalLibrary) -> None:
    _enable_memory(write_config)
    config = load_config(harness_root)
    service = MemoryService(FakeMemoryProvider(), project=config.project.name)
    service.add("Invoice rounding is half-even", scope=service.scope("project"),
                source=service.source("decision:D-1"))
    result = build_discovery(config, library, memory=service).discover(request("invoice rounding"))
    memory = [c for c in result.candidates if c.kind is CandidateKind.MEMORY]
    assert [c.id for c in memory] == ["memory/fake-000001"]
    assert result.candidates[-1] == memory[0]  # memory is listed last
    assert result.sources[-1].status is SourceStatus.OK


def test_memory_enabled_but_unopenable_is_unavailable(harness_root: Path, project: Path,
                                                      write_config: WriteConfig,
                                                      library: GlobalLibrary) -> None:
    _enable_memory(write_config)
    discovery = build_discovery(load_config(harness_root), library,
                                memory_unavailable="$MEM0_API_KEY is not set")
    report = discovery.discover(request()).sources[-1]
    assert (report.discoverer, report.status) == ("memory", SourceStatus.UNAVAILABLE)
    assert report.warnings == ("$MEM0_API_KEY is not set",)


def test_memory_outage_does_not_fail_discovery(harness_root: Path, project: Path,
                                               write_config: WriteConfig,
                                               library: GlobalLibrary) -> None:
    _enable_memory(write_config)
    config = load_config(harness_root)
    service = MemoryService(FakeMemoryProvider(unavailable=True), project=config.project.name)
    result = build_discovery(config, library, memory=service).discover(request("x"))
    assert result.sources[-1].status is SourceStatus.UNAVAILABLE
    assert "policy/secrets" in keys(result)


# --- configuration -----------------------------------------------------------------------------


def test_shipped_context_config() -> None:
    from orchestrator.config import default_harness_root

    config = load_config(default_harness_root())
    assert config.context.enabled is True
    settings = config.context.discovery
    assert "docs" in settings.documentation_paths and settings.adr_paths == ["docs/adr"]


def test_discovery_section_defaults(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext: {enabled: true}\n")
    settings = load_config(harness_root).context.discovery
    assert settings.instruction_files == [] and settings.documentation_paths == []
    assert settings.source_roots == ["."]
    assert settings.max_files == 5000 and settings.memory_results == 5


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("/etc", "relative POSIX path"),
        ("~/docs", "relative POSIX path"),
        ("../other", "must not contain '..'"),
        ("docs/../../x", "must not contain '..'"),
        ("docs\\\\adr", "relative POSIX path"),
        ("C:/docs", "relative POSIX path"),
    ],
)
def test_unsafe_configured_paths_are_rejected(harness_root: Path, write_config: WriteConfig,
                                              entry: str, message: str) -> None:
    write_config("context.yaml", f"""
        version: 1
        context:
          enabled: true
          discovery: {{documentation_paths: ["{entry}"]}}
    """)
    with pytest.raises(ConfigValidationError, match=message):
        load_config(harness_root)


@pytest.mark.parametrize("extra", ["budget: 100", "classification: true", "max_tokens: 10"])
def test_future_options_are_not_accepted(harness_root: Path, write_config: WriteConfig,
                                         extra: str) -> None:
    write_config(
        "context.yaml", f"version: 1\ncontext:\n  enabled: true\n  discovery:\n    {extra}\n"
    )
    with pytest.raises(ConfigValidationError, match="Extra inputs"):
        load_config(harness_root)


def test_paths_are_normalized(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", """
        version: 1
        context:
          enabled: true
          discovery: {documentation_paths: ["./docs/", "docs//adr"], source_roots: ["."]}
    """)
    settings = load_config(harness_root).context.discovery
    assert settings.documentation_paths == ["docs", "docs/adr"]
    assert settings.source_roots == ["."]


# --- doctor --------------------------------------------------------------------------------------


def _git_ok(args: object, *, cwd: Path | None = None, timeout: float | None = None
            ) -> CommandResult:
    return CommandResult(("git",), cwd, 0, "true\n", "", 0.0)


def test_doctor_context_passes_and_lists_absent_optional_paths(harness_root: Path,
                                                               project: Path) -> None:
    result = check_context(load_config(harness_root))
    assert result.status is CheckStatus.PASS
    assert result.detail.endswith("optional paths absent: CLAUDE.md")
    assert check_discovery_paths(load_config(harness_root)) == ("CLAUDE.md",)


def test_doctor_context_fails_on_escaping_path(harness_root: Path, project: Path,
                                               tmp_path_factory: pytest.TempPathFactory) -> None:
    (project / "docs" / "adr").rename(project / "old-adr")
    outside = tmp_path_factory.mktemp("out")
    (project / "docs" / "adr").symlink_to(outside, target_is_directory=True)
    report = run_doctor(harness_root, environ={}, runner=_git_ok, python_version=(3, 12, 0))
    result = {r.name: r for r in report.results}["context"]
    assert result.status is CheckStatus.FAIL
    assert "outside the project root" in result.detail


def test_doctor_skips_context_when_disabled(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext: {enabled: false}\n")
    report = run_doctor(harness_root, environ={}, runner=_git_ok, python_version=(3, 12, 0))
    assert "context" not in {r.name for r in report.results}


def test_doctor_never_runs_discovery(harness_root: Path, project: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("doctor must not walk the project")

    monkeypatch.setattr(ProjectFiles, "walk", forbidden)
    report = run_doctor(harness_root, environ={}, runner=_git_ok, python_version=(3, 12, 0))
    assert {r.name: r.status for r in report.results}["context"] is CheckStatus.PASS


# --- CLI -----------------------------------------------------------------------------------------


def test_cli_context_discover(harness_root: Path, project: Path, library_root: Path) -> None:
    write_artifact(library_root, "secrets", "policy")
    result = runner.invoke(
        app, ["--root", str(harness_root), "context", "discover", "edit billing/invoice.py",
              "--intent", "implement", "--ref", "T-9"],
        env={LIBRARY_ROOT_ENV: str(library_root)},
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["request"]["intent"] == "implement" and data["request"]["origin_ref"] == "T-9"
    ids = [c["id"] for c in data["candidates"]]
    assert ids[0] == "policy/secrets"
    assert "source/src/billing/invoice.py" in ids
    assert {s["discoverer"] for s in data["sources"]} == {
        "library", "instructions", "adrs", "documentation", "repository_hints", "memory",
    }
    assert "git" in data["unsupported_sources"]
    assert all(set(c) == {"id", "kind", "title", "reference", "provenance", "metadata"}
               for c in data["candidates"])


def test_cli_context_disabled_exits_1(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext: {enabled: false}\n")
    result = runner.invoke(app, ["--root", str(harness_root), "context", "discover", "x"],
                           env={LIBRARY_ROOT_ENV: ""})
    assert result.exit_code == 1
    assert "disabled" in result.stderr


def test_cli_memory_enabled_without_key_still_discovers(harness_root: Path, project: Path,
                                                        write_config: WriteConfig) -> None:
    _enable_memory(write_config)
    result = runner.invoke(app, ["--root", str(harness_root), "context", "discover", "x"],
                           env={LIBRARY_ROOT_ENV: "", "MEM0_API_KEY": ""})
    assert result.exit_code == 0, result.output
    memory = json.loads(result.stdout)["sources"][-1]
    assert memory["status"] == "unavailable"
    assert "MEM0_API_KEY" in memory["warnings"][0]


def test_cli_rejects_invalid_request(harness_root: Path) -> None:
    result = runner.invoke(app, ["--root", str(harness_root), "context", "discover", "   "])
    assert result.exit_code == 1
    assert "instruction" in result.stderr


# --- architecture guards -------------------------------------------------------------------


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


# V1.2: the probabilistic classifier may use the decision layer's typed contracts
# (never an adapter, the service, a registry or the network); nothing else may.
DECISION_CONTRACTS = {"orchestrator.decisions.models", "orchestrator.providers.base"}


def test_context_does_not_know_interfaces_providers_decisions_or_network() -> None:
    forbidden = ("orchestrator.cli", "orchestrator.doctor", "orchestrator.providers",
                 "orchestrator.decisions", "orchestrator.memory.service",
                 "orchestrator.memory.mem0", "orchestrator.memory.fake", "typer", "rich",
                 "urllib", "http", "socket", "subprocess", "orchestrator.utils.shell")
    probabilistic = PACKAGE / "context" / "classification" / "probabilistic.py"
    for path in (PACKAGE / "context").rglob("*.py"):
        allowed = DECISION_CONTRACTS if path == probabilistic else set()
        leaked = {n for n in _imports(path) if n.startswith(forbidden)} - allowed
        assert not leaked, f"{path} imports {leaked}"
    assert DECISION_CONTRACTS <= _imports(probabilistic)


def test_context_uses_no_execution_primitives() -> None:
    for path in (PACKAGE / "context").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert not calls & {"eval", "exec", "compile", "__import__"}, path


def test_earlier_context_stages_never_import_later_ones() -> None:
    """V1.1 discovery knows neither classification nor budget; V1.2 knows no budget (V1.3)."""
    later = {
        PACKAGE / "context": ("orchestrator.context.classification", "orchestrator.context.budget"),
        PACKAGE / "context" / "classification": ("orchestrator.context.budget",),
    }
    for directory, forbidden in later.items():
        for path in directory.glob("*.py"):
            assert not {n for n in _imports(path) if n.startswith(forbidden)}, path


def test_core_library_and_memory_do_not_depend_on_context() -> None:
    for package in ("core", "library", "memory"):
        for path in (PACKAGE / package).rglob("*.py"):
            assert not {n for n in _imports(path) if n.startswith("orchestrator.context")}, path

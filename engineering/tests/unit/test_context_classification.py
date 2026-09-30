"""V1.2 Context Classification: decision layer (offline fakes), precedence, fallback,
aggregation, composition/config, end to end, CLI and doctor."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from classification_helpers import (
    ScriptedDecisionProvider,
    candidate,
    decision_service,
    library,
    request,
)
from jev_emulator import JevEmulator
from library_helpers import write_artifact
from typer.testing import CliRunner

from orchestrator.cli import app
from orchestrator.config import HarnessConfig, load_config
from orchestrator.context.classification.classifier import ContextClassifier, build_classifier
from orchestrator.context.classification.models import (
    ContextClass,
    ContextClassificationResult,
    Evidence,
    SelectedBy,
)
from orchestrator.context.classification.probabilistic import (
    OPTIONS,
    QUESTION,
    REQUEST_CHARS,
    ProbabilisticClassifier,
    decision_subject,
)
from orchestrator.context.discovery import build_discovery
from orchestrator.context.models import (
    CandidateKind,
    ContextCandidate,
    ContextDiscoveryResult,
    ReferenceMatch,
    SourceReport,
    SourceStatus,
)
from orchestrator.core.exceptions import (
    ConfigValidationError,
    DecisionAuthenticationError,
    DecisionTimeoutError,
    DecisionUnavailableError,
)
from orchestrator.decisions.models import (
    DecisionOutcome,
    DecisionStatus,
    DecisionTelemetry,
)
from orchestrator.decisions.service import DecisionService, open_decisions
from orchestrator.doctor import CheckStatus, check_classification
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.loader import LIBRARY_ROOT_ENV
from orchestrator.providers.base import DecisionKind, DecisionResult
from orchestrator.providers.fake import FakeDecisionProvider

WriteConfig = Callable[[str, str], Path]
K = CandidateKind
runner = CliRunner()


def discovery(*candidates: ContextCandidate, text: str = "fix the invoice rounding"
              ) -> ContextDiscoveryResult:
    return ContextDiscoveryResult(request=request(text), candidates=candidates, sources=())


def probabilistic(provider: object, *, minimum: float = 0.7,
                  max_decisions: int = 50) -> ContextClassifier:
    service = decision_service(provider, minimum)  # type: ignore[arg-type]
    return ContextClassifier(
        probabilistic=ProbabilisticClassifier(service, max_decisions=max_decisions)
    )


def one(result: ContextClassificationResult, cid: str):  # type: ignore[no-untyped-def]
    return next(c.classification for c in result.candidates if c.candidate.id == cid)


POLICY = library(K.POLICY, "secrets", "mandatory")
DOC = candidate(K.DOCUMENTATION, "docs/overview.md", discoverer="documentation")
ADR = candidate(K.ADR, "docs/adr/0002.md", discoverer="adrs", metadata={"status": "Accepted"})
MEMORY = candidate(K.MEMORY, "m-1", discoverer="memory", metadata={
    "excerpt": "Invoices are rounded half-up in cents.", "lineage": "manual:ops",
    "backend_score": 0.83, "search_rank": 1, "source_of_truth": False,
})


# --- decision layer (fake providers, real DecisionService) ------------------------------------


@pytest.mark.parametrize("choice", ["HIGH_VALUE", "OPTIONAL", "EXCLUDED"])
def test_confident_decision_is_accepted(choice: str) -> None:
    provider = FakeDecisionProvider(choice=choice, confidence=0.92)
    k = one(probabilistic(provider).classify(discovery(DOC)), DOC.id)
    assert k.classification is ContextClass(choice)
    assert k.selected_by is SelectedBy.PROBABILISTIC
    assert k.evidence is Evidence.DECISION_PROVIDER_JUDGEMENT
    assert k.confidence == 0.92
    assert k.relevance == OPTIONS.index(choice) / 2  # ordered: EXCLUDED 0 .. HIGH_VALUE 1
    assert (k.provider, k.model) == ("fake-decision", "judge-v1")


def test_decision_request_is_minimal_ordered_and_never_offers_required() -> None:
    provider = FakeDecisionProvider()
    probabilistic(provider).classify(discovery(MEMORY, text="x" * 2000))
    (sent,) = provider.requests
    assert sent.question == QUESTION
    assert sent.options == ("EXCLUDED", "OPTIONAL", "HIGH_VALUE") and sent.ordered
    assert "REQUIRED" not in sent.options
    assert sent.kind is DecisionKind.CONTEXT_RELEVANCE
    assert set(sent.descriptions) == set(OPTIONS)
    subject = sent.subject or ""
    assert "Candidate kind: memory" in subject and "Excerpt: Invoices are rounded" in subject
    assert "Lineage: manual:ops" in subject
    assert "backend_score" not in subject.lower() and "0.83" not in subject
    assert "x" * REQUEST_CHARS + "..." in subject and "x" * (REQUEST_CHARS + 1) not in subject


def test_subject_lists_provenance_and_safe_metadata_only() -> None:
    doc = candidate(K.DOCUMENTATION, "docs/a.md", discoverer="documentation",
                    metadata={"size_bytes": 1234, "status": "Draft", "tags": ("a", "b")})
    subject = decision_subject(request("write docs"), doc)
    assert subject.splitlines()[:4] == [
        "Request (intent: unclassified): write docs", "Candidate kind: doc",
        "Title: docs/a.md", "Reference: project:docs/a.md",
    ]
    assert "Found by documentation: via documentation" in subject
    assert "Status: Draft" in subject and "Tags: a, b" in subject
    assert "1234" not in subject


def test_low_confidence_falls_back_to_optional_with_the_suggestion() -> None:
    provider = FakeDecisionProvider(choice="EXCLUDED", confidence=0.55)
    result = probabilistic(provider, minimum=0.7).classify(discovery(DOC))
    k = one(result, DOC.id)
    assert (k.classification, k.selected_by, k.evidence) == (
        ContextClass.OPTIONAL, SelectedBy.FALLBACK, Evidence.DECISION_LOW_CONFIDENCE,
    )
    assert (k.suggestion, k.confidence, k.provider) == (ContextClass.EXCLUDED, 0.55,
                                                        "fake-decision")
    assert "below the minimum 0.70" in k.reason
    assert result.warnings == ()  # an expected outcome, not a problem


def test_invalid_choice_is_rejected_by_the_decision_layer() -> None:
    provider = FakeDecisionProvider(choice="REQUIRED")  # not an allowed option
    result = probabilistic(provider).classify(discovery(DOC, ADR))
    assert {one(result, c).evidence for c in (DOC.id, ADR.id)} == {
        Evidence.DECISION_INVALID_RESPONSE
    }
    assert result.counts[ContextClass.REQUIRED] == 0
    assert len(provider.requests) == 2  # invalid answers do not stop the run
    assert all("broke the decision contract" in w for w in result.warnings)


class RogueDecider:
    """A Decider that bypasses DecisionService validation and claims REQUIRED."""

    provider_id = "rogue"

    def decide(self, **kwargs: object) -> DecisionOutcome:
        result = DecisionResult(provider="rogue", model="m", choice="REQUIRED", confidence=1.0)
        telemetry = DecisionTelemetry(
            timestamp=datetime(2026, 9, 30, tzinfo=UTC), provider="rogue", model_alias="d",
            model="m", kind=DecisionKind.CONTEXT_RELEVANCE, option_count=3,
            status=DecisionStatus.DECIDED, minimum_confidence=0.7, fallback_required=False,
            duration_ms=0,
        )
        return DecisionOutcome(status=DecisionStatus.DECIDED, kind=DecisionKind.CONTEXT_RELEVANCE,
                               result=result, telemetry=telemetry)


def test_required_can_never_come_from_the_probabilistic_layer() -> None:
    classifier = ContextClassifier(
        probabilistic=ProbabilisticClassifier(RogueDecider(), max_decisions=5)  # type: ignore[arg-type]
    )
    result = classifier.classify(discovery(DOC))
    k = one(result, DOC.id)
    assert (k.classification, k.evidence) == (ContextClass.OPTIONAL,
                                              Evidence.DECISION_INVALID_RESPONSE)
    assert "not allowed" in result.warnings[0]


@pytest.mark.parametrize("error", [DecisionUnavailableError, DecisionTimeoutError])
def test_unavailable_provider_is_not_called_again_and_is_reported(
    error: type[DecisionUnavailableError],
) -> None:
    provider = FakeDecisionProvider(fail_with="service down", fail_as=error)
    result = probabilistic(provider).classify(discovery(DOC, ADR, MEMORY))
    assert len(provider.requests) == 1
    assert {c.classification.evidence for c in result.candidates} == {
        Evidence.DECISION_UNAVAILABLE
    }
    assert result.counts[ContextClass.OPTIONAL] == 3
    assert any("service down" in w for w in result.warnings)
    assert any("2 further candidate(s) were not sent" in w for w in result.warnings)


def test_raised_provider_error_is_a_visible_fallback_not_a_crash() -> None:
    provider = FakeDecisionProvider(fail_with="key rejected", fail_as=DecisionAuthenticationError)
    result = probabilistic(provider).classify(discovery(POLICY, DOC, ADR))
    assert len(provider.requests) == 1
    assert one(result, POLICY.id).classification is ContextClass.REQUIRED
    assert one(result, DOC.id).evidence is Evidence.DECISION_UNAVAILABLE
    assert any("key rejected" in w for w in result.warnings)


def test_max_decisions_bounds_the_calls() -> None:
    docs = [candidate(K.DOCUMENTATION, f"docs/{i}.md") for i in range(4)]
    provider = FakeDecisionProvider(choice="HIGH_VALUE")
    result = probabilistic(provider, max_decisions=2).classify(discovery(*docs))
    assert len(provider.requests) == 2
    assert result.decisions == {SelectedBy.DETERMINISTIC: 0, SelectedBy.PROBABILISTIC: 2,
                                SelectedBy.FALLBACK: 2}
    assert any("max_decisions (2) reached: 2 candidate(s)" in w for w in result.warnings)


def test_sensitive_decision_input_is_never_sent() -> None:
    provider = FakeDecisionProvider()
    secret_request = "rotate ghp_" + "a" * 36 + " in the deploy script"
    result = probabilistic(provider).classify(discovery(DOC, text=secret_request))
    assert provider.requests == []
    assert one(result, DOC.id).evidence is Evidence.UNSAFE_DECISION_INPUT
    assert "github_token" in result.warnings[0] and "ghp_" not in result.warnings[0]


# --- precedence ------------------------------------------------------------------------------


def test_deterministic_decisions_are_never_sent_to_the_decision_layer() -> None:
    explicit = candidate(K.SOURCE_CODE, "src/invoice.py", discoverer="repository_hints",
                         match=ReferenceMatch.PATH)
    provider = FakeDecisionProvider(choice="EXCLUDED", confidence=1.0)
    result = probabilistic(provider).classify(discovery(POLICY, explicit, DOC))
    assert len(provider.requests) == 1
    assert "docs/overview.md" in (provider.requests[0].subject or "")
    assert one(result, POLICY.id).classification is ContextClass.REQUIRED
    assert one(result, explicit.id).classification is ContextClass.REQUIRED
    assert one(result, DOC.id).classification is ContextClass.EXCLUDED


def test_memory_never_outranks_an_official_source() -> None:
    provider = ScriptedDecisionProvider({"Candidate kind: memory": ("HIGH_VALUE", 0.99)})
    result = probabilistic(provider).classify(discovery(POLICY, MEMORY))
    ids = [c.candidate.id for c in result.candidates]
    assert ids == ["policy/secrets", "memory/m-1"]
    assert one(result, MEMORY.id).classification is ContextClass.HIGH_VALUE
    assert one(result, POLICY.id).classification is ContextClass.REQUIRED


# --- aggregation -----------------------------------------------------------------------------


def _mixed_discovery() -> ContextDiscoveryResult:
    superseded = candidate(K.ADR, "docs/adr/0001.md", discoverer="adrs",
                           metadata={"status": "Superseded by ADR-0002"})
    guideline = library(K.GUIDELINE, "testing", "recommended")
    return discovery(POLICY, guideline, superseded, ADR, DOC, MEMORY)


def _scripted() -> ScriptedDecisionProvider:
    return ScriptedDecisionProvider({
        "docs/adr/0002.md": ("HIGH_VALUE", 0.9),
        "docs/overview.md": ("EXCLUDED", 0.85),
        "Candidate kind: memory": ("HIGH_VALUE", 0.4),  # below threshold
    })


def test_mixed_classification_counts_and_order() -> None:
    result = probabilistic(_scripted()).classify(_mixed_discovery())
    assert [(c.candidate.id, c.classification.classification.value,
             c.classification.selected_by.value) for c in result.candidates] == [
        ("policy/secrets", "REQUIRED", "deterministic"),
        ("guideline/testing", "HIGH_VALUE", "deterministic"),
        ("adr/docs/adr/0002.md", "HIGH_VALUE", "probabilistic"),
        ("memory/m-1", "OPTIONAL", "fallback"),
        ("adr/docs/adr/0001.md", "EXCLUDED", "deterministic"),
        ("doc/docs/overview.md", "EXCLUDED", "probabilistic"),
    ]
    assert result.counts == {ContextClass.REQUIRED: 1, ContextClass.HIGH_VALUE: 2,
                             ContextClass.OPTIONAL: 1, ContextClass.EXCLUDED: 2}
    assert result.decisions == {SelectedBy.DETERMINISTIC: 3, SelectedBy.PROBABILISTIC: 2,
                                SelectedBy.FALLBACK: 1}
    assert result.decision_provider == "scripted"


def test_every_candidate_is_kept_and_untouched() -> None:
    source = _mixed_discovery()
    result = probabilistic(_scripted()).classify(source)
    assert sorted(c.candidate.id for c in result.candidates) == sorted(
        c.id for c in source.candidates
    )
    by_id = {c.id: c for c in source.candidates}
    assert all(c.candidate == by_id[c.candidate.id] for c in result.candidates)
    assert result.counts[ContextClass.EXCLUDED] == 2  # visible, not filtered


def test_classification_is_identical_between_runs() -> None:
    source = _mixed_discovery()
    first = probabilistic(_scripted()).classify(source)
    second = probabilistic(_scripted()).classify(source)
    assert first == second and first.model_dump_json() == second.model_dump_json()


def test_without_decision_layer_unresolved_candidates_fall_back_with_a_warning() -> None:
    source = _mixed_discovery()
    result = ContextClassifier(unavailable_reason="decision layer unavailable: disabled").classify(
        source
    )
    fallbacks = [c for c in result.candidates
                 if c.classification.selected_by is SelectedBy.FALLBACK]
    assert {c.candidate.id for c in fallbacks} == {ADR.id, DOC.id, MEMORY.id}
    assert {c.classification.evidence for c in fallbacks} == {Evidence.NO_DECISION_LAYER}
    assert result.decision_provider is None
    assert result.warnings == (
        "classification: 3 candidate(s) without a deterministic rule use the conservative "
        "fallback (OPTIONAL): decision layer unavailable: disabled",
    )


def test_discovery_warnings_are_carried_over() -> None:
    report = SourceReport(discoverer="adrs", status=SourceStatus.OK, candidates=0,
                          warnings=("'docs/adr' does not exist",))
    source = ContextDiscoveryResult(request=request(), candidates=(POLICY,), sources=(report,))
    assert ContextClassifier().classify(source).warnings == ("adrs: 'docs/adr' does not exist",)


# --- composition and configuration ---------------------------------------------------------------


def test_shipped_classification_config() -> None:
    from orchestrator.config import default_harness_root

    settings = load_config(default_harness_root()).context.classification
    assert settings.probabilistic is True and settings.max_decisions == 50


def test_classification_section_defaults(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext: {enabled: true}\n")
    settings = load_config(harness_root).context.classification
    assert settings.probabilistic is True and settings.max_decisions == 50


@pytest.mark.parametrize("entry", ["max_decisions: 0", "budget: 100", "confidence_threshold: 0.8"])
def test_invalid_or_unknown_classification_options_are_rejected(
    harness_root: Path, write_config: WriteConfig, entry: str,
) -> None:
    write_config("context.yaml",
                 f"version: 1\ncontext:\n  enabled: true\n  classification:\n    {entry}\n")
    with pytest.raises(ConfigValidationError):
        load_config(harness_root)


def test_build_classifier_respects_probabilistic_false(harness_root: Path,
                                                       write_config: WriteConfig) -> None:
    write_config("context.yaml", """
        version: 1
        context: {enabled: true, classification: {probabilistic: false}}
    """)
    provider = FakeDecisionProvider()
    classifier = build_classifier(load_config(harness_root), decider=decision_service(provider))
    result = classifier.classify(discovery(DOC))
    assert provider.requests == []
    assert "disabled in context.yaml" in one(result, DOC.id).reason


def test_build_classifier_uses_the_decider_and_max_decisions(harness_root: Path,
                                                             write_config: WriteConfig) -> None:
    write_config("context.yaml", """
        version: 1
        context: {enabled: true, classification: {max_decisions: 1}}
    """)
    provider = FakeDecisionProvider(choice="HIGH_VALUE")
    classifier = build_classifier(load_config(harness_root), decider=decision_service(provider))
    classifier.classify(discovery(DOC, ADR))
    assert len(provider.requests) == 1


def test_build_classifier_without_decider_reports_why(harness_root: Path) -> None:
    classifier = build_classifier(load_config(harness_root),
                                  decider_unavailable="provider 'jev' is not enabled")
    result = classifier.classify(discovery(DOC))
    assert "provider 'jev' is not enabled" in one(result, DOC.id).reason


# --- end to end: request -> discovery -> classification ---------------------------------------


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(harness_root: Path, write_config: WriteConfig, library_root: Path) -> Path:
    root = harness_root.parent
    touch(root / "AGENTS.md", "# Agents\n")
    touch(root / "docs" / "overview.md", "# Overview\n")
    touch(root / "docs" / "adr" / "0001-cents.md",
          "# ADR-0001: Cents\n- Status: Superseded by ADR-0002\n")
    touch(root / "docs" / "adr" / "0002-banker.md", "# ADR-0002: Banker\n- Status: Accepted\n")
    touch(root / "src" / "billing" / "invoice.py")
    touch(root / "src" / "billing" / "tax.py")
    touch(root / "src" / "billing" / "uv.lock")
    write_config("context.yaml", """
        version: 1
        context:
          enabled: true
          discovery:
            instruction_files: [AGENTS.md]
            documentation_paths: [docs]
            adr_paths: [docs/adr]
            source_roots: [src]
            exclude_dirs: [harness, library]
    """)
    write_artifact(library_root, "secrets", "policy")
    write_artifact(library_root, "testing", "guideline")
    write_artifact(library_root, "python", "skill", applies_to="  stacks: [python]")
    write_artifact(library_root, "debugging", "skill")
    return root


E2E_REQUEST = "fix rounding in src/billing/ per docs/adr/0001-cents.md"


def _e2e(harness_root: Path, library_root: Path) -> ContextClassificationResult:
    config = load_config(harness_root)
    found = build_discovery(config, GlobalLibrary.load(library_root)).discover(request(E2E_REQUEST))
    provider = ScriptedDecisionProvider({
        "0002-banker.md": ("HIGH_VALUE", 0.88),
        "docs/overview.md": ("EXCLUDED", 0.8),
        "skills/debugging.md": ("OPTIONAL", 0.75),
    })
    return build_classifier(config, decider=decision_service(provider)).classify(found)


def test_end_to_end_all_four_classes(harness_root: Path, project: Path,
                                     library_root: Path) -> None:
    result = _e2e(harness_root, library_root)
    table = {c.candidate.id: (c.classification.classification.value,
                              c.classification.evidence.value) for c in result.candidates}
    assert table == {
        "policy/secrets": ("REQUIRED", "applicable_policy"),
        "instructions/AGENTS.md": ("REQUIRED", "project_instruction"),
        "adr/docs/adr/0001-cents.md": ("EXCLUDED", "superseded_adr"),  # named, still EXCLUDED
        "guideline/testing": ("HIGH_VALUE", "applicable_guideline"),
        "skill/python": ("HIGH_VALUE", "matching_stack"),
        "adr/docs/adr/0002-banker.md": ("HIGH_VALUE", "decision_provider_judgement"),
        "source/src/billing/invoice.py": ("HIGH_VALUE", "named_directory_entry"),
        "source/src/billing/tax.py": ("HIGH_VALUE", "named_directory_entry"),
        "skill/debugging": ("OPTIONAL", "decision_provider_judgement"),
        "doc/docs/overview.md": ("EXCLUDED", "decision_provider_judgement"),
        "source/src/billing/uv.lock": ("EXCLUDED", "generated_artifact"),
    }
    assert result.counts == {ContextClass.REQUIRED: 2, ContextClass.HIGH_VALUE: 5,
                             ContextClass.OPTIONAL: 1, ContextClass.EXCLUDED: 3}
    assert result.decisions == {SelectedBy.DETERMINISTIC: 8, SelectedBy.PROBABILISTIC: 3,
                                SelectedBy.FALLBACK: 0}


def test_dedup_regression_explicit_superseded_adr_keeps_all_evidence(
    harness_root: Path, project: Path, library_root: Path,
) -> None:
    """V1.1 debt: one ADR found by adrs + documentation + repository_hints."""
    result = _e2e(harness_root, library_root)
    adr = next(c for c in result.candidates if c.candidate.id == "adr/docs/adr/0001-cents.md")
    assert {p.discoverer for p in adr.candidate.provenance} == {
        "adrs", "documentation", "repository_hints",
    }
    assert adr.candidate.metadata["status"] == "Superseded by ADR-0002"
    # Negative structural state wins over the explicit reference, which stays auditable.
    assert adr.classification.classification is ContextClass.EXCLUDED
    assert adr.classification.evidence is Evidence.SUPERSEDED_ADR
    assert adr.classification.also_matched == (Evidence.EXPLICIT_DOCUMENT_REFERENCE,)


def test_end_to_end_does_not_depend_on_cwd(harness_root: Path, project: Path, library_root: Path,
                                           tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config(harness_root)
    found = build_discovery(config, GlobalLibrary.load(library_root)).discover(request(E2E_REQUEST))
    expected = build_classifier(config).classify(found)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config = load_config(harness_root)
    again = build_discovery(config, GlobalLibrary.load(library_root)).discover(found.request)
    assert build_classifier(config).classify(again) == expected


# --- CLI ------------------------------------------------------------------------------------------


def test_cli_classify_offline_with_decision_provider_disabled(
    harness_root: Path, project: Path, library_root: Path,
) -> None:
    result = runner.invoke(
        app, ["--root", str(harness_root), "context", "classify", E2E_REQUEST, "--ref", "T-1"],
        env={LIBRARY_ROOT_ENV: str(library_root)},
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["decision_provider"] is None
    assert data["request"]["origin_ref"] == "T-1"
    assert sum(data["counts"].values()) == len(data["candidates"])
    assert data["decisions"]["probabilistic"] == 0
    for item in data["candidates"]:
        assert set(item) == {"candidate", "classification"}
        assert {"classification", "selected_by", "evidence", "reason", "confidence"} <= set(
            item["classification"]
        )
    assert any("decision layer unavailable" in w and "jev" in w for w in data["warnings"])
    assert "budget" not in result.stdout.lower()


def test_cli_classify_with_jev_emulated(harness_root: Path, project: Path, library_root: Path,
                                        write_config: WriteConfig,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    write_config("providers.yaml", """
        version: 1
        providers:
          jev: {kind: jev, enabled: true}
    """)
    emulator = JevEmulator(pick="HIGH_VALUE")

    def opener(config: HarnessConfig) -> DecisionService:
        return open_decisions(config, {"JEV_API_KEY": "test-key-not-a-secret"},
                              transport=emulator)

    monkeypatch.setattr("orchestrator.cli.open_decisions", opener)
    result = runner.invoke(app, ["--root", str(harness_root), "context", "classify", E2E_REQUEST],
                           env={LIBRARY_ROOT_ENV: str(library_root)})
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["decision_provider"] == "jev"
    judged = [c for c in data["candidates"]
              if c["classification"]["selected_by"] == "probabilistic"]
    assert {c["candidate"]["id"] for c in judged} == {
        "adr/docs/adr/0002-banker.md", "doc/docs/overview.md", "skill/debugging",
    }
    assert all(c["classification"]["classification"] == "HIGH_VALUE"
               and c["classification"]["provider"] == "jev" for c in judged)


def test_cli_classify_disabled_context_exits_1(harness_root: Path,
                                               write_config: WriteConfig) -> None:
    write_config("context.yaml", "version: 1\ncontext: {enabled: false}\n")
    result = runner.invoke(app, ["--root", str(harness_root), "context", "classify", "x"],
                           env={LIBRARY_ROOT_ENV: ""})
    assert result.exit_code == 1 and "disabled" in result.stderr


def test_cli_classify_rejects_invalid_request(harness_root: Path) -> None:
    result = runner.invoke(app, ["--root", str(harness_root), "context", "classify", "  "])
    assert result.exit_code == 1 and "instruction" in result.stderr


def test_cli_help_lists_classify() -> None:
    result = runner.invoke(app, ["context", "--help"])
    assert result.exit_code == 0 and "classify" in result.stdout and "discover" in result.stdout


# --- doctor (structural only) ---------------------------------------------------------------------


def _doctor(harness_root: Path) -> tuple[CheckStatus, str]:
    result = check_classification(load_config(harness_root))
    return result.status, result.detail


def test_doctor_shipped_config_reports_disabled_provider(harness_root: Path) -> None:
    status, detail = _doctor(harness_root)
    assert status is CheckStatus.PASS and "'jev' is disabled" in detail and "OPTIONAL" in detail


def test_doctor_probabilistic_false(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("context.yaml", """
        version: 1
        context: {enabled: true, classification: {probabilistic: false}}
    """)
    status, detail = _doctor(harness_root)
    assert status is CheckStatus.PASS and "deterministic rules only" in detail


def test_doctor_warns_without_decision_model(harness_root: Path, write_config: WriteConfig) -> None:
    write_config("decisions.yaml", """
        version: 1
        decisions: {escalation_order: [deterministic, human]}
    """)
    status, detail = _doctor(harness_root)
    assert status is CheckStatus.WARN and "no model" in detail


def test_doctor_enabled_provider_is_structural(harness_root: Path, write_config: WriteConfig,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    write_config("providers.yaml", """
        version: 1
        providers:
          jev: {kind: jev, enabled: true}
    """)

    def forbidden(*args: object, **kwargs: Mapping[str, str]) -> None:
        raise AssertionError("classification check must not open the decision layer")

    monkeypatch.setattr("orchestrator.doctor.open_decisions", forbidden)
    status, detail = _doctor(harness_root)
    assert status is CheckStatus.PASS
    assert "decision model 'decision'" in detail and "minimum_confidence 0.70" in detail

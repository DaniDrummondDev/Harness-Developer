"""V1.2 deterministic classification: each rule, its precedence and its limits."""

from __future__ import annotations

import pytest
from classification_helpers import candidate, library, request

from orchestrator.context.classification.deterministic import (
    DEFAULT_RULES,
    ClassificationRule,
    DeterministicClassifier,
)
from orchestrator.context.classification.models import (
    DETERMINISTIC_EVIDENCE,
    ContextClass,
    Evidence,
    SelectedBy,
)
from orchestrator.context.discoverers import LibraryDiscoverer
from orchestrator.context.models import CandidateKind, ContextCandidate, ReferenceMatch
from orchestrator.library.library import GlobalLibrary
from orchestrator.library.loader import resolve_library_root
from orchestrator.library.models import ProjectProfile

classifier = DeterministicClassifier()
K = CandidateKind


def decide(c: ContextCandidate) -> tuple[ContextClass, Evidence] | None:
    result = classifier.classify(c)
    if result is None:
        return None
    assert result.selected_by is SelectedBy.DETERMINISTIC and result.reason
    return result.classification, result.evidence


def hinted(kind: CandidateKind, path: str, match: ReferenceMatch,
           **metadata: str) -> ContextCandidate:
    return candidate(kind, path, discoverer="repository_hints", match=match, metadata=metadata)


# --- REQUIRED ------------------------------------------------------------------------------------


def test_applicable_policy_is_required() -> None:
    assert decide(library(K.POLICY, "secrets", "mandatory")) == (
        ContextClass.REQUIRED, Evidence.APPLICABLE_POLICY,
    )


def test_policy_named_explicitly_keeps_the_policy_rule_and_records_the_reference() -> None:
    result = classifier.classify(library(K.POLICY, "git", "mandatory", match=ReferenceMatch.PATH))
    assert result is not None and result.evidence is Evidence.APPLICABLE_POLICY
    assert result.also_matched == (Evidence.EXPLICIT_LIBRARY_REFERENCE,)


@pytest.mark.parametrize("match", [ReferenceMatch.PATH, ReferenceMatch.FILE_NAME])
def test_explicit_source_reference_is_required(match: ReferenceMatch) -> None:
    assert decide(hinted(K.SOURCE_CODE, "src/billing/invoice.py", match)) == (
        ContextClass.REQUIRED, Evidence.EXPLICIT_SOURCE_REFERENCE,
    )


@pytest.mark.parametrize("kind", [K.DOCUMENTATION, K.ADR, K.PROJECT_INSTRUCTIONS])
def test_explicit_document_reference_is_required(kind: CandidateKind) -> None:
    doc = candidate(kind, "docs/x.md", discoverer="documentation", extra=hinted(
        K.SOURCE_CODE, "docs/x.md", ReferenceMatch.PATH).provenance)
    assert decide(doc) == (ContextClass.REQUIRED, Evidence.EXPLICIT_DOCUMENT_REFERENCE)


def test_explicit_library_reference_is_required() -> None:
    skill = library(K.SKILL, "security", "knowledge", match=ReferenceMatch.FILE_NAME)
    assert decide(skill) == (ContextClass.REQUIRED, Evidence.EXPLICIT_LIBRARY_REFERENCE)


def test_project_instruction_is_required() -> None:
    assert decide(candidate(K.PROJECT_INSTRUCTIONS, "CLAUDE.md", discoverer="instructions")) == (
        ContextClass.REQUIRED, Evidence.PROJECT_INSTRUCTION,
    )


# --- EXCLUDED ------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["Superseded by ADR-0003", "deprecated", "**Rejected**",
                                    "Obsolete since 2025"])
def test_inactive_adr_is_excluded(status: str) -> None:
    adr = candidate(K.ADR, "docs/adr/0001.md", discoverer="adrs", metadata={"status": status})
    assert decide(adr) == (ContextClass.EXCLUDED, Evidence.SUPERSEDED_ADR)


@pytest.mark.parametrize("status", ["Accepted", "Proposed", "Accepted (supersedes ADR-0001)"])
def test_active_adr_is_not_resolved_deterministically(status: str) -> None:
    adr = candidate(K.ADR, "docs/adr/0002.md", discoverer="adrs", metadata={"status": status})
    assert decide(adr) is None  # existence is not relevance: left to Jev / fallback


def explicit_adr(status: str) -> ContextCandidate:
    return candidate(K.ADR, "docs/adr/0001.md", discoverer="adrs", metadata={"status": status},
                     extra=hinted(K.SOURCE_CODE, "docs/adr/0001.md",
                                  ReferenceMatch.PATH).provenance)


@pytest.mark.parametrize("status", ["Superseded by ADR-0003", "Deprecated", "rejected",
                                    "Obsolete since 2025"])
def test_explicit_reference_does_not_revive_an_inactive_adr(status: str) -> None:
    """Negative structural state takes precedence over an explicit reference."""
    result = classifier.classify(explicit_adr(status))
    assert result is not None
    assert (result.classification, result.selected_by, result.evidence) == (
        ContextClass.EXCLUDED, SelectedBy.DETERMINISTIC, Evidence.SUPERSEDED_ADR,
    )
    assert result.also_matched == (Evidence.EXPLICIT_DOCUMENT_REFERENCE,)


@pytest.mark.parametrize("status", ["Accepted", "Proposed"])
def test_explicit_reference_to_an_active_adr_is_required(status: str) -> None:
    result = classifier.classify(explicit_adr(status))
    assert result is not None
    assert (result.classification, result.evidence) == (
        ContextClass.REQUIRED, Evidence.EXPLICIT_DOCUMENT_REFERENCE,
    )
    assert result.also_matched == ()


@pytest.mark.parametrize("path", ["engineering/uv.lock", "package-lock.json",
                                  "public/app.min.js", "public/app.js.map", "go.sum"])
def test_generated_file_in_a_named_directory_is_excluded(path: str) -> None:
    result = classifier.classify(hinted(K.SOURCE_CODE, path, ReferenceMatch.DIRECTORY))
    assert result is not None
    assert (result.classification, result.evidence) == (
        ContextClass.EXCLUDED, Evidence.GENERATED_ARTIFACT,
    )
    assert result.also_matched == (Evidence.NAMED_DIRECTORY_ENTRY,)


@pytest.mark.parametrize("match", [ReferenceMatch.PATH, ReferenceMatch.FILE_NAME])
@pytest.mark.parametrize("path", ["engineering/uv.lock", "public/app.min.js",
                                  "public/app.min.css", "public/app.js.map"])
def test_generated_file_named_explicitly_stays_excluded(path: str,
                                                        match: ReferenceMatch) -> None:
    result = classifier.classify(hinted(K.SOURCE_CODE, path, match))
    assert result is not None
    assert (result.classification, result.selected_by, result.evidence) == (
        ContextClass.EXCLUDED, SelectedBy.DETERMINISTIC, Evidence.GENERATED_ARTIFACT,
    )
    assert result.also_matched == (Evidence.EXPLICIT_SOURCE_REFERENCE,)


def test_normal_source_file_named_explicitly_is_still_required() -> None:
    result = classifier.classify(hinted(K.SOURCE_CODE, "src/billing/invoice.py",
                                        ReferenceMatch.PATH))
    assert result is not None
    assert (result.classification, result.evidence, result.also_matched) == (
        ContextClass.REQUIRED, Evidence.EXPLICIT_SOURCE_REFERENCE, (),
    )


def test_negative_rules_precede_explicit_references_in_the_table() -> None:
    order = [rule.id for rule in DEFAULT_RULES]
    assert order.index(Evidence.SUPERSEDED_ADR) < order.index(Evidence.EXPLICIT_DOCUMENT_REFERENCE)
    assert order.index(Evidence.GENERATED_ARTIFACT) < order.index(
        Evidence.EXPLICIT_SOURCE_REFERENCE
    )


# --- HIGH_VALUE ----------------------------------------------------------------------------------


def test_applicable_guideline_and_library_rule_are_high_value() -> None:
    assert decide(library(K.GUIDELINE, "testing", "recommended")) == (
        ContextClass.HIGH_VALUE, Evidence.APPLICABLE_GUIDELINE,
    )
    assert decide(library(K.RULE, "thin-controllers", "recommended", "stack:laravel")) == (
        ContextClass.HIGH_VALUE, Evidence.APPLICABLE_LIBRARY_RULE,
    )


@pytest.mark.parametrize("kind", [K.SKILL, K.SPECIALTY])
def test_knowledge_matching_the_profile_is_high_value(kind: CandidateKind) -> None:
    assert decide(library(kind, "python", "knowledge", "stack:python")) == (
        ContextClass.HIGH_VALUE, Evidence.MATCHING_STACK,
    )
    assert decide(library(kind, "api", "knowledge", "capability:api")) == (
        ContextClass.HIGH_VALUE, Evidence.MATCHING_CAPABILITY,
    )


@pytest.mark.parametrize("kind", [K.SKILL, K.SPECIALTY])
def test_general_knowledge_is_not_resolved_deterministically(kind: CandidateKind) -> None:
    assert decide(library(kind, "testing", "knowledge", "always")) is None


def test_file_in_a_named_directory_is_high_value() -> None:
    assert decide(hinted(K.SOURCE_CODE, "src/billing/tax.py", ReferenceMatch.DIRECTORY)) == (
        ContextClass.HIGH_VALUE, Evidence.NAMED_DIRECTORY_ENTRY,
    )


# --- not deterministic ---------------------------------------------------------------------------


def test_ambiguous_file_name_is_left_to_the_decision_layer() -> None:
    assert decide(hinted(K.SOURCE_CODE, "src/other/invoice.py",
                         ReferenceMatch.AMBIGUOUS_FILE_NAME)) is None


def test_document_merely_under_docs_is_not_resolved() -> None:
    doc = candidate(K.DOCUMENTATION, "docs/overview.md", discoverer="documentation")
    assert decide(doc) is None


def test_authority_is_read_from_metadata_not_derived_from_the_kind() -> None:
    no_authority = candidate(K.POLICY, "secrets", discoverer="library")
    assert decide(no_authority) is None
    guideline_without_authority = candidate(K.GUIDELINE, "coding", discoverer="library")
    assert decide(guideline_without_authority) is None


def test_memory_is_never_required_even_with_misleading_metadata() -> None:
    memory = candidate(K.MEMORY, "m-1", discoverer="memory",
                       metadata={"authority": "mandatory", "excerpt": "we always use cents"})
    assert decide(memory) is None


def test_candidate_without_any_signal_does_not_break_the_classifier() -> None:
    odd = candidate(K.SOURCE_CODE, "x.py", discoverer="future_source",
                    metadata={"unknown": "value", "numbers": 3})
    assert decide(odd) is None


# --- rule table ---------------------------------------------------------------------------------


def test_rule_table_ids_are_unique_stable_and_all_deterministic() -> None:
    ids = [rule.id for rule in DEFAULT_RULES]
    assert len(ids) == len(set(ids))
    assert set(ids) == DETERMINISTIC_EVIDENCE
    assert ids[0] is Evidence.APPLICABLE_POLICY


def test_classifier_rejects_duplicate_or_non_deterministic_rules() -> None:
    rule = DEFAULT_RULES[0]
    with pytest.raises(ValueError, match="unique"):
        DeterministicClassifier([rule, rule])
    bogus = ClassificationRule(Evidence.NO_DECISION_LAYER, ContextClass.OPTIONAL, "x",
                               lambda c: True)
    with pytest.raises(ValueError, match="not deterministic"):
        DeterministicClassifier([bogus])


def test_classification_is_deterministic() -> None:
    c = hinted(K.SOURCE_CODE, "src/a.py", ReferenceMatch.PATH)
    assert classifier.classify(c) == classifier.classify(c)


# --- against the real Global Library -------------------------------------------------------------


def test_real_library_for_a_python_project() -> None:
    library_ = GlobalLibrary.load(resolve_library_root())
    found = LibraryDiscoverer(library_, ProjectProfile(stack=("python",))).discover(request())
    decided = {c.id: decide(c) for c in found.candidates}
    required = {cid for cid, d in decided.items() if d and d[0] is ContextClass.REQUIRED}
    assert required == {c.id for c in found.candidates if c.kind is K.POLICY}
    assert all(decided[c.id] == (ContextClass.HIGH_VALUE, Evidence.APPLICABLE_GUIDELINE)
               for c in found.candidates if c.kind is K.GUIDELINE)
    assert decided["rule/validation-at-boundaries"] == (
        ContextClass.HIGH_VALUE, Evidence.APPLICABLE_LIBRARY_RULE,
    )
    assert decided["skill/python"] == (ContextClass.HIGH_VALUE, Evidence.MATCHING_STACK)
    assert decided["specialty/python"] == (ContextClass.HIGH_VALUE, Evidence.MATCHING_STACK)
    unresolved = {cid for cid, d in decided.items() if d is None}
    assert unresolved == {"skill/security", "skill/testing", "specialty/architecture",
                          "specialty/security", "specialty/testing"}

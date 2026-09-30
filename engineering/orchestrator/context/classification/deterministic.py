"""Deterministic classification rules (V1.2): objective evidence -> class.

A `ClassificationRule` is a Harness decision rule. It is NOT a Global Library
`rule` artifact (kind `rule`, e.g. "thin controllers"): those are knowledge the
rules below may classify (`applicable_library_rule`).

Rules are evaluated in this order; the FIRST match decides, later matches are
recorded in `also_matched`. The order is the precedence:

    #  rule (stable id)             class       evidence used
    1  applicable_policy            REQUIRED    metadata authority == mandatory (library
                                                resolved it for the project profile)
    2  superseded_adr               EXCLUDED    ADR metadata status superseded /
                                                deprecated / rejected / obsolete
    3  generated_artifact           EXCLUDED    project file that is a lock file, minified
                                                bundle or source map
    4  explicit_source_reference    REQUIRED    source file whose provenance match is PATH
                                                or FILE_NAME (named in request/origin_ref)
    5  explicit_document_reference  REQUIRED    same, for instructions / ADR / doc
    6  explicit_library_reference   REQUIRED    same, for a library artifact file
    7  project_instruction          REQUIRED    kind instructions (configured
                                                discovery.instruction_files)
    8  applicable_guideline         HIGH_VALUE  guideline, authority recommended
    9  applicable_library_rule      HIGH_VALUE  library rule, authority recommended
    10 matching_stack               HIGH_VALUE  knowledge (skill/specialty) applying via
                                                a declared stack (`applies` stack:*)
    11 matching_capability          HIGH_VALUE  knowledge applying via a declared capability
    12 named_directory_entry        HIGH_VALUE  file inside a directory named in the request

Why this order: a negative structural state takes precedence over an explicit
reference. Naming a superseded ADR or a lock file in the request does not make
it REQUIRED: obsolete context and generated artifacts stay EXCLUDED, and the
reference is kept in `also_matched` (audit: why excluded, and that it was
named). Exclusions also beat the generic HIGH_VALUE rules. Applicable policies
come first; they are library artifacts, which no exclusion rule targets.

Deliberately NOT deterministic (left to the probabilistic layer, else OPTIONAL):
documentation merely found under `docs/`, accepted/proposed ADRs not named in
the request, knowledge that applies `always` (general skills/specialties),
memories, and ambiguous file-name matches. Existence is not relevance.

A memory is never REQUIRED: rules that would make it so are skipped, and the
result model rejects it as well.

To add a rule: add an `Evidence` member (models.py), append a
`ClassificationRule` at the right precedence position, document it in the table
above and add positive/negative tests in tests/unit/test_context_classification_rules.py.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from orchestrator.context.classification.models import (
    DETERMINISTIC_EVIDENCE,
    ContextClass,
    ContextClassification,
    Evidence,
    SelectedBy,
)
from orchestrator.context.models import (
    CandidateKind,
    ContextCandidate,
    ReferenceMatch,
    ReferenceStore,
)
from orchestrator.library.models import Authority

_LIBRARY_KINDS = frozenset({
    CandidateKind.POLICY, CandidateKind.GUIDELINE, CandidateKind.RULE, CandidateKind.SKILL,
    CandidateKind.SPECIALTY,
})
_DOCUMENT_KINDS = frozenset({
    CandidateKind.PROJECT_INSTRUCTIONS, CandidateKind.ADR, CandidateKind.DOCUMENTATION,
})
_EXPLICIT_MATCHES = frozenset({ReferenceMatch.PATH, ReferenceMatch.FILE_NAME})
_INACTIVE_ADR_STATUS = re.compile(r"^\W*(superseded|deprecated|rejected|obsolete)\b", re.IGNORECASE)
_GENERATED_NAMES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "poetry.lock", "uv.lock", "pipfile.lock", "cargo.lock", "gemfile.lock", "go.sum",
})
_GENERATED_SUFFIXES = (".min.js", ".min.css", ".map", ".lock")


# --- predicates over the V1.1 model (no re-derivation from directory names) ------------------


def _text(candidate: ContextCandidate, key: str) -> str | None:
    value = candidate.metadata.get(key)
    return value if isinstance(value, str) else None


def _applies(candidate: ContextCandidate) -> tuple[str, ...]:
    value = candidate.metadata.get("applies")
    return value if isinstance(value, tuple) else ()


def _authority_is(authority: Authority) -> Callable[[ContextCandidate], bool]:
    return lambda candidate: _text(candidate, "authority") == authority


def _matched(candidate: ContextCandidate, matches: frozenset[ReferenceMatch]) -> bool:
    return any(p.match in matches for p in candidate.provenance)


def _explicit(kinds: frozenset[CandidateKind]) -> Callable[[ContextCandidate], bool]:
    return lambda candidate: candidate.kind in kinds and _matched(candidate, _EXPLICIT_MATCHES)


def _generated(candidate: ContextCandidate) -> bool:
    if candidate.reference.store is not ReferenceStore.PROJECT:
        return False
    name = PurePosixPath(candidate.reference.path).name.lower()
    return name in _GENERATED_NAMES or name.endswith(_GENERATED_SUFFIXES)


def _inactive_adr(candidate: ContextCandidate) -> bool:
    status = _text(candidate, "status")
    return (candidate.kind is CandidateKind.ADR and status is not None
            and bool(_INACTIVE_ADR_STATUS.match(status)))


def _knowledge_applying_via(prefix: str) -> Callable[[ContextCandidate], bool]:
    return lambda candidate: (
        _text(candidate, "authority") == Authority.KNOWLEDGE
        and any(reason.startswith(prefix) for reason in _applies(candidate))
    )


# --- rules -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassificationRule:
    id: Evidence
    classification: ContextClass
    description: str
    applies: Callable[[ContextCandidate], bool]


DEFAULT_RULES: tuple[ClassificationRule, ...] = (
    ClassificationRule(
        Evidence.APPLICABLE_POLICY, ContextClass.REQUIRED,
        "mandatory library policy that applies to the project profile",
        _authority_is(Authority.MANDATORY),
    ),
    # Negative structural state: evaluated before explicit references (never promoted).
    ClassificationRule(
        Evidence.SUPERSEDED_ADR, ContextClass.EXCLUDED,
        "ADR whose status is superseded, deprecated, rejected or obsolete", _inactive_adr,
    ),
    ClassificationRule(
        Evidence.GENERATED_ARTIFACT, ContextClass.EXCLUDED,
        "generated file (lock file, minified bundle or source map)", _generated,
    ),
    ClassificationRule(
        Evidence.EXPLICIT_SOURCE_REFERENCE, ContextClass.REQUIRED,
        "source file named explicitly in the request",
        _explicit(frozenset({CandidateKind.SOURCE_CODE})),
    ),
    ClassificationRule(
        Evidence.EXPLICIT_DOCUMENT_REFERENCE, ContextClass.REQUIRED,
        "document named explicitly in the request", _explicit(_DOCUMENT_KINDS),
    ),
    ClassificationRule(
        Evidence.EXPLICIT_LIBRARY_REFERENCE, ContextClass.REQUIRED,
        "library artifact named explicitly in the request", _explicit(_LIBRARY_KINDS),
    ),
    ClassificationRule(
        Evidence.PROJECT_INSTRUCTION, ContextClass.REQUIRED,
        "configured project instruction file",
        lambda c: c.kind is CandidateKind.PROJECT_INSTRUCTIONS,
    ),
    ClassificationRule(
        Evidence.APPLICABLE_GUIDELINE, ContextClass.HIGH_VALUE,
        "recommended guideline that applies to the project profile",
        lambda c: c.kind is CandidateKind.GUIDELINE and _authority_is(Authority.RECOMMENDED)(c),
    ),
    ClassificationRule(
        Evidence.APPLICABLE_LIBRARY_RULE, ContextClass.HIGH_VALUE,
        "recommended library rule that applies to the project profile",
        lambda c: c.kind is CandidateKind.RULE and _authority_is(Authority.RECOMMENDED)(c),
    ),
    ClassificationRule(
        Evidence.MATCHING_STACK, ContextClass.HIGH_VALUE,
        "skill/specialty for a stack the project declares", _knowledge_applying_via("stack:"),
    ),
    ClassificationRule(
        Evidence.MATCHING_CAPABILITY, ContextClass.HIGH_VALUE,
        "skill/specialty for a capability the project declares",
        _knowledge_applying_via("capability:"),
    ),
    ClassificationRule(
        Evidence.NAMED_DIRECTORY_ENTRY, ContextClass.HIGH_VALUE,
        "file inside a directory named in the request",
        lambda c: _matched(c, frozenset({ReferenceMatch.DIRECTORY})),
    ),
)


class DeterministicClassifier:
    def __init__(self, rules: Sequence[ClassificationRule] = DEFAULT_RULES) -> None:
        ids = [rule.id for rule in rules]
        if len(set(ids)) != len(ids):
            raise ValueError(f"classification rule ids must be unique: {ids}")
        unknown = [str(i) for i in ids if i not in DETERMINISTIC_EVIDENCE]
        if unknown:
            raise ValueError(f"not deterministic evidence: {unknown}")
        self._rules = tuple(rules)

    @property
    def rules(self) -> tuple[ClassificationRule, ...]:
        return self._rules

    def classify(self, candidate: ContextCandidate) -> ContextClassification | None:
        """The first matching rule decides; None = no objective evidence."""
        matched = [rule for rule in self._rules if rule.applies(candidate)]
        if candidate.kind is CandidateKind.MEMORY:  # memory is never a source of truth
            matched = [rule for rule in matched if rule.classification is not ContextClass.REQUIRED]
        if not matched:
            return None
        decisive = matched[0]
        return ContextClassification(
            classification=decisive.classification, selected_by=SelectedBy.DETERMINISTIC,
            evidence=decisive.id, reason=decisive.description,
            also_matched=tuple(rule.id for rule in matched[1:]),
        )

"""`ContextClassifier`: ContextDiscoveryResult -> ContextClassificationResult (V1.2).

    each candidate (from V1.1 discovery, untouched)
      -> DeterministicClassifier   first matching rule decides      (never overridden)
      -> unresolved only:
           ProbabilisticClassifier  decision layer (Jev), if available and enabled
           or fallback              OPTIONAL, evidence no_decision_layer
      -> ContextClassificationResult.build: every candidate kept (EXCLUDED too),
         ordered by class, kind, id; counts; warnings

Precedence is structural: a candidate resolved by a deterministic rule is never
sent to the decision layer, so no probabilistic answer can downgrade (or
upgrade) it; and the decision layer cannot produce REQUIRED at all.

`build_classifier(config, decider=...)` is the composition step. Opening the
decision layer (API key, provider) is left to the caller (CLI), like memory for
discovery; a caller that could not open it passes the reason as
`decider_unavailable` and classification goes on deterministically.
"""

from __future__ import annotations

from orchestrator.config import HarnessConfig
from orchestrator.context.classification.deterministic import DeterministicClassifier
from orchestrator.context.classification.models import (
    FALLBACK_CLASS,
    ClassifiedContextCandidate,
    ContextClassification,
    ContextClassificationResult,
    Evidence,
)
from orchestrator.context.classification.probabilistic import Decider, ProbabilisticClassifier
from orchestrator.context.models import ContextCandidate, ContextDiscoveryResult


class ContextClassifier:
    def __init__(
        self,
        *,
        deterministic: DeterministicClassifier | None = None,
        probabilistic: ProbabilisticClassifier | None = None,
        unavailable_reason: str = "no decision layer is available",
    ) -> None:
        self._deterministic = deterministic or DeterministicClassifier()
        self._probabilistic = probabilistic
        self._unavailable_reason = unavailable_reason

    def classify(self, discovery: ContextDiscoveryResult) -> ContextClassificationResult:
        decided: list[tuple[ContextCandidate, ContextClassification]] = []
        unresolved: list[ContextCandidate] = []
        for candidate in discovery.candidates:
            classification = self._deterministic.classify(candidate)
            if classification is None:
                unresolved.append(candidate)
            else:
                decided.append((candidate, classification))

        warnings = list(discovery.warnings)
        if unresolved and self._probabilistic is not None:
            results, run_warnings = self._probabilistic.classify(discovery.request, unresolved)
            decided.extend(zip(unresolved, results, strict=True))
            warnings.extend(f"classification: {w}" for w in run_warnings)
        elif unresolved:
            fallback = ContextClassification.fallback(
                Evidence.NO_DECISION_LAYER,
                f"no deterministic rule matched; {self._unavailable_reason}",
            )
            decided.extend((candidate, fallback) for candidate in unresolved)
            warnings.append(
                f"classification: {len(unresolved)} candidate(s) without a deterministic rule use "
                f"the conservative fallback ({FALLBACK_CLASS}): {self._unavailable_reason}"
            )

        return ContextClassificationResult.build(
            discovery.request,
            [ClassifiedContextCandidate(candidate=c, classification=k) for c, k in decided],
            warnings=warnings,
            decision_provider=self._probabilistic.provider_id if self._probabilistic else None,
        )


def build_classifier(
    config: HarnessConfig,
    *,
    decider: Decider | None = None,
    decider_unavailable: str | None = None,
) -> ContextClassifier:
    """Compose the classifier for `config` (context.yaml `classification`).

    The decider is used only when `classification.probabilistic` is true. Its
    threshold is decisions.yaml `thresholds.minimum_confidence`, applied by the
    decider itself (DecisionService)."""
    settings = config.context.classification
    if not settings.probabilistic:
        return ContextClassifier(
            unavailable_reason="probabilistic classification is disabled in context.yaml"
        )
    if decider is None:
        reason = decider_unavailable or "not provided"
        return ContextClassifier(unavailable_reason=f"decision layer unavailable: {reason}")
    return ContextClassifier(
        probabilistic=ProbabilisticClassifier(decider, max_decisions=settings.max_decisions)
    )

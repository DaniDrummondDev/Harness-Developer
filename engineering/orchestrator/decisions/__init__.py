"""Decision foundation (V0.4): the probabilistic decision layer, on top of `DecisionProvider`.

    models.py   DecisionOutcome (DECIDED | FALLBACK_REQUIRED), FallbackReason,
                DecisionTelemetry, DecisionHealth (typed, auditable data)
    service.py  DecisionService (boundary validation + thresholds + fallback
                signalling + telemetry) and open_decisions(config) composition

Position in the decision hierarchy (decisions.yaml `escalation_order`):

    1. deterministic rules   -- always first, never overridden (RNF-030)
    2. probabilistic (Jev)   -- THIS package, V0.4
    3. reasoning LLM         -- V5
    4. human                 -- V5, final authority

Jev is probabilistic: a high confidence (even 1.0) is a model's belief, never a
proof or a deterministic rule. This package only *signals* that a fallback is
required; it never calls an LLM or a human, and it never combines layers (that
is the Decision Policy Engine, V5). `core/` does not import this package.
"""

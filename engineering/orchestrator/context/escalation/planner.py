"""`ContextEscalation` and `ContextPlanner` (V1.4): budget -> escalation result.

    ContextBudgetResult (V1.3, never modified)
      -> EscalationEvaluator (deterministic)
           not required ──────────────────────────> NOT_REQUIRED, 0 LLM calls
      -> harness_constraints + prepare_input (safe allow-list, secret checks)
           no planner (no model / disabled / no adapter) -> FAILED planner_unavailable, 0 calls
           request or final prompt unsafe ────────> FAILED unsafe_input, 0 calls
      -> LLMProvider.complete (via ModelResolver: alias -> provider -> model id)
           ProviderError (timeout, 5xx, auth...) ─> FAILED provider_error, 1 call
      -> parse_response + validate_plan (deterministic)
           invalid ───────────────────────────────> FAILED invalid_output, 1 call
           valid ─────────────────────────────────> PLANNED (ContextPlan), 1 call

Fallback is always the V1.3 result carried in `ContextEscalationResult.budget`:
never another LLM, never Jev, never an automatic human review (V5/V6).

Composition: `open_context_planner(config, registry)` resolves context.yaml
`escalation.model` through `ModelResolver`; an adapter already in `registry`
(tests: a scripted LLMProvider) is used, otherwise `build_llm_adapter` builds one
from providers.yaml. No LLM adapter exists yet (real ones: V2.x), so without an
injected registry the planner is unavailable and escalations end FAILED with
the deterministic result kept.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from orchestrator.config import HarnessConfig, ProviderEntry
from orchestrator.context.budget.models import ContextBudgetResult
from orchestrator.context.escalation.evaluator import EscalationEvaluator
from orchestrator.context.escalation.models import (
    ContextEscalationDecision,
    ContextEscalationResult,
    PlannerCall,
    PlanningFailure,
    PlanStatus,
    UnresolvedConstraint,
)
from orchestrator.context.escalation.planning import (
    harness_constraints,
    prepare_input,
    render_prompt,
)
from orchestrator.context.escalation.validation import (
    InvalidPlanError,
    parse_response,
    validate_plan,
)
from orchestrator.core.exceptions import (
    ProviderError,
    ProviderNotEnabledError,
    ProviderNotFoundError,
)
from orchestrator.memory import safety
from orchestrator.providers.base import LLMProvider, LLMRequest
from orchestrator.providers.registry import ProviderRegistry
from orchestrator.providers.resolution import ModelResolver, ResolvedModel

logger = logging.getLogger(__name__)

# Provider kinds with a concrete LLMProvider adapter. Empty in V1.4: OpenAI,
# Anthropic and NVIDIA adapters arrive in V2.x. `jev` is a DecisionProvider only.
LLM_ADAPTER_KINDS: frozenset[str] = frozenset()
DECISION_ONLY_KINDS: frozenset[str] = frozenset({"jev"})


class ContextPlanner:
    def __init__(self, llm: LLMProvider, model: ResolvedModel, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._llm = llm
        self._model = model
        self._clock = clock

    @property
    def model(self) -> ResolvedModel:
        return self._model

    def plan(self, budget: ContextBudgetResult,
             decision: ContextEscalationDecision) -> ContextEscalationResult:
        constraints = harness_constraints(budget)
        prepared = prepare_input(budget, decision, constraints)
        known = (*constraints, *prepared.withheld)
        if prepared.input is None:
            return _failed(budget, decision, known, PlanningFailure.UNSAFE_INPUT,
                           "the request instruction failed the safety check (rules: "
                           f"{', '.join(prepared.blocked_rules)}); nothing was sent")
        prompt = render_prompt(prepared.input)
        if rules := safety.evaluate(prompt).rules:
            return _failed(budget, decision, known, PlanningFailure.UNSAFE_INPUT,
                           f"the planner prompt failed the safety check (rules: {', '.join(rules)}"
                           "); nothing was sent")

        started = self._clock()
        try:
            answer = self._llm.complete(LLMRequest(model=self._model.model_id, prompt=prompt))
        except ProviderError as exc:
            call = self._call(started, len(prompt), None)
            return _failed(budget, decision, known, PlanningFailure.PROVIDER_ERROR, str(exc),
                           call=call)
        call = self._call(started, len(prompt), len(answer.text))
        try:
            plan = validate_plan(parse_response(answer.text), budget, prepared.input,
                                 constraints=known,
                                 withheld_mandatory=prepared.withheld_mandatory)
        except InvalidPlanError as exc:
            return _failed(budget, decision, known, PlanningFailure.INVALID_OUTPUT,
                           f"planner output rejected: {exc}", call=call)
        logger.info("context plan: %d selected, %d added, %d dropped (%s/%s)",
                    len(plan.selected_candidate_ids), len(plan.added), len(plan.dropped),
                    call.provider, call.model_alias)
        return ContextEscalationResult(
            budget=budget, escalation=decision, status=PlanStatus.PLANNED, constraints=known,
            plan=plan, call=call, llm_calls=1,
            warnings=(*budget.warnings, *_constraint_warnings(known)),
        )

    def _call(self, started: float, prompt_characters: int,
              response_characters: int | None) -> PlannerCall:
        return PlannerCall(
            model_alias=self._model.alias, provider=self._model.provider,
            model_id=self._model.model_id,
            duration_ms=max(0, round((self._clock() - started) * 1000)),
            prompt_characters=prompt_characters, response_characters=response_characters,
        )


class ContextEscalation:
    """Evaluate triggers; call the planner only when one fired."""

    def __init__(self, evaluator: EscalationEvaluator, planner: ContextPlanner | None = None, *,
                 unavailable_reason: str = "no planner model is configured") -> None:
        self._evaluator = evaluator
        self._planner = planner
        self._unavailable_reason = unavailable_reason

    def escalate(self, budget: ContextBudgetResult) -> ContextEscalationResult:
        decision = self._evaluator.evaluate(budget)
        if not decision.required:
            note = () if decision.evaluated else (
                "escalation: disabled in context.yaml; triggers were not evaluated",)
            return ContextEscalationResult(budget=budget, escalation=decision,
                                           status=PlanStatus.NOT_REQUIRED,
                                           warnings=(*budget.warnings, *note))
        if self._planner is None:
            constraints = harness_constraints(budget)
            return _failed(budget, decision, constraints, PlanningFailure.PLANNER_UNAVAILABLE,
                           self._unavailable_reason)
        return self._planner.plan(budget, decision)


def _failed(budget: ContextBudgetResult, decision: ContextEscalationDecision,
            constraints: tuple[UnresolvedConstraint, ...], kind: PlanningFailure, detail: str, *,
            call: PlannerCall | None = None) -> ContextEscalationResult:
    logger.info("context escalation failed (%s); the deterministic budget result stands", kind)
    return ContextEscalationResult(
        budget=budget, escalation=decision, status=PlanStatus.FAILED, constraints=constraints,
        failure_kind=kind, failure=detail, call=call, llm_calls=0 if call is None else 1,
        warnings=(
            *budget.warnings,
            f"escalation: required ({', '.join(decision.reasons)}) but planning failed "
            f"({kind}): {detail}; the deterministic budget result stands",
            *_constraint_warnings(constraints),
        ),
    )


def _constraint_warnings(constraints: tuple[UnresolvedConstraint, ...]) -> tuple[str, ...]:
    return tuple(f"escalation: unresolved {c.kind}: {c.detail}" for c in constraints)


# --- composition ----------------------------------------------------------------------------


def build_llm_adapter(provider_id: str, entry: ProviderEntry) -> LLMProvider:
    """providers.yaml entry -> concrete LLMProvider. None exists in V1.4 (V2.x)."""
    available = ", ".join(sorted(LLM_ADAPTER_KINDS)) or "none yet; LLM adapters arrive in V2.x"
    raise ProviderNotFoundError(
        f"provider '{provider_id}' has kind '{entry.kind}', which has no LLM adapter "
        f"(available: {available})"
    )


def open_context_planner(config: HarnessConfig,
                         registry: ProviderRegistry | None = None) -> ContextPlanner:
    """The configured planner. Fails closed without any network call:
    ProviderNotEnabledError (no model), ModelNotFoundError / ProviderNotEnabledError
    (resolution), ProviderNotFoundError (no adapter), ProviderTypeMismatchError."""
    alias = config.context.escalation.model
    if alias is None:
        raise ProviderNotEnabledError(
            "no planner model is configured (set context.yaml escalation.model to a models.yaml "
            "alias whose provider has an LLM adapter)"
        )
    registry = registry if registry is not None else ProviderRegistry()
    resolver = ModelResolver(models=config.models, providers=config.providers, registry=registry)
    resolved = resolver.resolve(alias)
    if resolved.provider not in registry:
        registry.register_llm(build_llm_adapter(resolved.provider,
                                                config.providers[resolved.provider]))
    llm, model = resolver.llm(alias)
    return ContextPlanner(llm, model)


def build_escalation(config: HarnessConfig, *, planner: ContextPlanner | None = None,
                     planner_unavailable: str | None = None) -> ContextEscalation:
    """Compose escalation for `config` (context.yaml `escalation`). Opening the planner
    is the caller's step (like the decision layer for classification)."""
    return ContextEscalation(
        EscalationEvaluator(config.context.escalation), planner,
        unavailable_reason=planner_unavailable or "no planner model is configured",
    )

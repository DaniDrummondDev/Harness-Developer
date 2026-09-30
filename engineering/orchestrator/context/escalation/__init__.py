"""LLM Context Escalation (V1.4): does this request need a reasoning model to plan
its context, and if so, which validated `ContextPlan` does it propose?

    models.py      contracts (EscalationReason, ContextEscalationDecision, ContextPlan,
                   UnresolvedConstraint, PlannerCall, ContextEscalationResult)
    invariants.py  PlanningRole + plan_violations (what any plan must respect)
    evaluator.py   EscalationEvaluator: deterministic triggers over the V1.3 result
    planning.py    ContextPlanningInput (safe allow-list), constraints, prompt
    validation.py  strict JSON parsing + invariant enforcement of the planner output
    planner.py     ContextPlanner (LLMProvider), ContextEscalation (evaluate -> maybe
                   plan) and composition (open_context_planner, build_escalation)

Default path: deterministic. The LLM is called only when a trigger fires, only
through `LLMProvider` + `ModelResolver`, only with safety-checked metadata (never
candidate content), and its output is validated before it exists. It cannot
reclassify, drop REQUIRED, select EXCLUDED or hide an overflow. On any failure
the V1.3 budget result stands. Nothing here renders an agent prompt (V2+).
"""

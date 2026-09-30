"""Context Engineering (V1.x).

V1.1 Context Candidate Discovery: `discovery.py` (service + composition),
`discoverers.py` (one class per real source), `files.py` (safe, bounded
filesystem access), `models.py` (contracts). Discovery only finds; it never
classifies.

V1.2 Context Classification: `classification/` labels each discovered candidate
REQUIRED / HIGH_VALUE / OPTIONAL / EXCLUDED.

V1.3 Context Budget: `budget/` selects, whole items only, the classified
candidates that fit a character budget.

V1.4 LLM Context Escalation: `escalation/` decides deterministically whether the
budget result needs a reasoning model and, only then, asks the planner model for a
validated `ContextPlan`. Nothing here renders an agent prompt (V2+).
Each stage consumes the previous one's result and never imports a later stage.
"""

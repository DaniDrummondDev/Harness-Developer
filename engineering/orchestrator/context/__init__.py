"""Context Engineering (V1.x).

V1.1 Context Candidate Discovery: `discovery.py` (service + composition),
`discoverers.py` (one class per real source), `files.py` (safe, bounded
filesystem access), `models.py` (contracts). Discovery only finds; it never
classifies.

V1.2 Context Classification: `classification/` labels each discovered candidate
REQUIRED / HIGH_VALUE / OPTIONAL / EXCLUDED. Nothing here budgets or selects
context for a prompt (V1.3+).
"""

"""Context Budget (V1.3): which classified candidates fit, whole, in a character
budget — and why each one does or does not.

    models.py    contracts (BudgetCategory, BudgetStatus, BudgetReason, BudgetedItem,
                 LimitConflict, BudgetUsage, ContextBudgetResult) and their invariants
    content.py   ContentLoader protocol + ContextContentLoader (reference -> safe text)
    budgeter.py  ContextBudgeter (REQUIRED -> HIGH_VALUE -> OPTIONAL; EXCLUDED never)
                 and build_budgeter(config, library) composition

The class from V1.2 is the input and the authority: nothing here reclassifies,
calls Jev or an LLM. REQUIRED is never dropped; a REQUIRED set that does not fit
is an explicit status (REQUIRED_OVERFLOW / REQUIRED_UNAVAILABLE). Nothing here
renders a prompt (V2+) or asks what to remove (V1.4).
"""

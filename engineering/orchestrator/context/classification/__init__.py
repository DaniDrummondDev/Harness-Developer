"""Context Classification (V1.2): every discovered candidate gets exactly one of
REQUIRED / HIGH_VALUE / OPTIONAL / EXCLUDED, with who decided and why.

    models.py         contracts (ContextClass, SelectedBy, Evidence,
                      ContextClassification, ClassifiedContextCandidate,
                      ContextClassificationResult) and their invariants
    deterministic.py  ClassificationRule table + DeterministicClassifier (first match wins)
    probabilistic.py  Decider protocol (DecisionService fits) + ProbabilisticClassifier
    classifier.py     ContextClassifier (deterministic -> decision layer -> fallback)
                      and build_classifier(config) composition

Only `probabilistic.py` knows the decision layer, and only through its typed
contracts (`decisions.models`, `providers.base`): no adapter, SDK or network.
Nothing here budgets, truncates or selects context for a prompt (V1.3+).
"""

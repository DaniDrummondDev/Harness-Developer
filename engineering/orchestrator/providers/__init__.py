"""Provider abstraction (V0.2): contracts, registry, model resolution and fakes.

    base.py        LLMProvider / DecisionProvider contracts + typed request/result
    registry.py    ProviderRegistry: provider id -> adapter, per contract
    resolution.py  ModelResolver: model alias -> provider -> model id -> adapter
    fake.py        deterministic offline adapters for tests

Callers use the contracts in `base.py` and a `ModelResolver`; they never
name a vendor. `core/` does not import this package. Concrete vendor adapters (OpenAI,
Anthropic, NVIDIA, Jev) are added as new modules here when their integration
version arrives; no vendor SDK is imported in V0.2.
"""

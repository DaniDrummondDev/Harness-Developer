"""Long-term operational memory (V0.3): contract, safety policy, adapters, service.

    models.py   scopes, lineage, records, queries, health (typed contract data)
    base.py     MemoryProvider contract (Protocol)
    safety.py   safe ingestion policy: ALLOW / BLOCK, deterministic, fail closed
    service.py  MemoryService (validation + policy + provider) and open_memory(config)
    mem0.py     Mem0 self-hosted REST adapter (the only module that knows Mem0)
    fake.py     deterministic in-process provider for tests

Memory is auxiliary context and never a source of truth: official docs, ADRs,
policies, task/sprint contracts and Git always take precedence (resolving
conflicts between them is Context Engineering, V1.x). `core/` does not import
this package, and nothing writes memory automatically in V0.3.
"""

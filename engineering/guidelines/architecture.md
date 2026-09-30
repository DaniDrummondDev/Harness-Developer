---
version: 1
id: architecture
type: guideline
name: Architecture practices
description: Respect module boundaries and dependency direction, record decisions in ADRs, evolve incrementally.
tags: [architecture, design]
applies_to:
  always: true
---
# Guideline: Architecture practices

Recommended practice. ADRs and policies take precedence over it.

- **Respect boundaries.** Dependencies point one way (interface -> application -> domain);
  the domain does not import frameworks, transport or vendors.
- **Adapters at the edge.** External services (LLMs, databases, queues, HTTP APIs) are
  reached through adapters so they can be replaced and faked in tests.
- **Decisions are recorded.** A choice that constrains future work gets an ADR with context,
  options, decision and consequences. Do not change an accepted ADR silently.
- **Incremental evolution.** Build what the current version needs; prepare for change
  without implementing the future (see rule `avoid-unnecessary-abstractions`).
- **Explicit contracts** between modules: typed inputs/outputs, documented errors.
- **Deterministic first.** Objective conditions are decided by code, not by a model.
- When a task needs an architectural change it did not declare, stop and escalate.

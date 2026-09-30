---
version: 1
id: breaking-changes
type: policy
name: Breaking changes
description: Changes that break a public contract, persisted data or configuration require an explicit human decision and a migration path.
tags: [compatibility, contracts, process]
applies_to:
  always: true
---
# Policy: Breaking changes

Mandatory. A breaking change is never made silently.

A change is **breaking** when an existing, correct consumer stops working without changing
its own code or data. Examples: removing or renaming a public API field, endpoint, CLI
command, config key or event; tightening validation of accepted input; changing the meaning
of a stored value; a destructive or non-reversible migration.

1. Identify it: every task states whether it touches a public contract, persisted data or
   configuration.
2. Prefer additive evolution (new optional fields, new versions) over modification.
3. A breaking change requires an explicit human decision, recorded (ADR or task decision),
   before implementation.
4. It ships with a migration path (deprecation window, versioned contract, migration
   script) and a rollback plan.
5. Release notes call it out explicitly.

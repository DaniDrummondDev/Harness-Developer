---
version: 1
id: architecture
type: specialty
name: Software architecture
description: Boundaries, dependency direction, contracts, trade-offs and architectural decision records.
tags: [architecture, design]
applies_to:
  always: true
rules: [avoid-unnecessary-abstractions, validation-at-boundaries]
---
# Specialty: Software architecture

**Profile.** Knowledge of module boundaries, dependency rules, contracts between components,
trade-off analysis and decision records. Complements guideline `architecture`.

**Checklist**
- Does the change respect existing boundaries and dependency direction?
- Is every new abstraction justified by a current consumer?
- Are contracts explicit, typed and versioned where they cross boundaries?
- Does the change contradict an ADR? If so, it needs a new decision, not a silent edit.
- Are failure modes, rollback and observability considered?

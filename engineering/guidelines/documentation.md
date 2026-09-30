---
version: 1
id: documentation
type: guideline
name: Documentation expectations
description: Keep docs true to the code - document what exists, why decisions were made, and how to operate and debug.
tags: [documentation]
applies_to:
  always: true
---
# Guideline: Documentation expectations

Recommended practice.

- **Document what exists.** Architecture docs separate the current state from the target
  architecture; never describe unimplemented features as done.
- Update docs in the same change that alters behaviour, configuration or operation.
- Record *why*: decisions and trade-offs belong in ADRs or sprint records.
- Each module states its responsibility and its boundaries in its docstring.
- Operational docs cover setup, commands, exit codes, configuration and how to debug.
- Keep examples runnable and free of real secrets.
- Prefer one authoritative place per fact; link instead of copying.

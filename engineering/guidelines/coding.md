---
version: 1
id: coding
type: guideline
name: Coding conventions
description: General coding conventions - clarity over cleverness, small units, explicit errors, typed boundaries.
tags: [code-quality]
applies_to:
  always: true
---
# Guideline: Coding conventions

Recommended practice. Project guidelines and task contracts may refine it; policies override it.

- **Clarity over cleverness.** Code is read far more than written; prefer the obvious version.
- **Match the surrounding code**: naming, idioms, comment density and structure.
- **Small units** with one responsibility; a function name states what it does.
- **Explicit errors.** Raise typed/domain errors with actionable messages; never swallow
  exceptions silently. Unexpected failures surface, expected ones are handled.
- **Types at boundaries.** Public functions and data crossing modules are typed and validated.
- **No magic values.** Name constants; keep configuration out of code.
- **No dead code** or commented-out blocks; Git keeps history.
- **Comments explain why**, not what the next line does.
- Keep diffs focused on the task; refactors travel in their own change.

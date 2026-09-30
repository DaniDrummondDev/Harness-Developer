---
version: 1
id: validation-at-boundaries
type: rule
name: Validation at boundaries
description: Validate and normalize external input once, at the trust boundary, into typed values; the core trusts only validated types.
tags: [security, design, validation]
applies_to:
  always: true
---
# Rule: Validation at boundaries

**Instruction.** Data entering the system (HTTP, CLI, files, config, queues, third-party
responses, LLM output) is validated and converted into typed domain values at the boundary
where it enters. Invalid input is rejected there with a clear error; inner layers receive
only validated types.

**Verifiable by**
- each entry point has a schema/validator (request object, Pydantic model, form request...);
- tests submit invalid, missing and extra fields and expect rejection;
- core functions accept typed values, not raw dicts/strings from outside.

**Why.** One validation point is auditable; scattered ad-hoc checks drift and leave gaps.

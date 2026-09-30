---
version: 1
id: security
type: policy
name: Security baseline
description: Non-negotiable security baseline for every change - least privilege, input validation, safe execution and fail-closed defaults.
tags: [security]
applies_to:
  always: true
---
# Policy: Security baseline

Mandatory for every change, in every project.

1. **Fail closed.** For authentication, authorization, integrity or deployment decisions,
   missing evidence means *deny*, never implicit approval.
2. **Least privilege.** Code, services, tokens and agents get only the permissions the
   current step needs.
3. **Untrusted input is validated** at every trust boundary (HTTP, CLI, files, queues,
   webhooks, LLM output) before use.
4. **No dynamic execution of untrusted data:** no `eval`/`exec`, no shell interpolation of
   user input, no unsafe deserialization (`pickle`, unsafe YAML loaders).
5. **Queries are parameterized.** String-built SQL, shell or template code is forbidden.
6. **Authorization is explicit** on every protected operation; hiding a route is not access
   control.
7. **Dependencies** come from trusted registries with pinned or bounded versions; known
   critical vulnerabilities block release.
8. A detected security issue escalates to a human; it is never silently accepted.

---
version: 1
id: security
type: specialty
name: Application security
description: Threat modelling, authentication/authorization, input handling, secrets and dependency security.
tags: [security]
applies_to:
  always: true
skills: [security]
rules: [explicit-authorization, validation-at-boundaries]
---
# Specialty: Application security

**Profile.** Application-level security: threat modelling, OWASP-class vulnerabilities,
authentication and authorization design, secret management, secure execution of files and
commands, supply-chain hygiene. Policies `security` and `secrets` are the mandatory baseline.

**Checklist**
- Who can reach the changed code, with what input? Is every path authorized?
- Is all external input validated and all output encoded for its context?
- Are secrets absent from code, config, logs and prompts?
- Are file paths and commands constrained to a safe root/allowlist?

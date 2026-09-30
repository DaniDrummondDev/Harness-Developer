---
version: 1
id: security
type: skill
name: Secure implementation
description: How to implement and review changes securely - threat-model the change, validate input, authorize, protect secrets.
tags: [security]
applies_to:
  always: true
---
# Skill: Secure implementation

**Use when** a change touches input handling, authentication/authorization, data access,
secrets, file/command execution or dependencies. Policy `security` sets the mandatory
baseline; this skill is the how-to.

**How to do it well**
1. Threat-model the change in one minute: who can call it, with what input, what could
   they reach or change?
2. Validate input at the boundary (rule `validation-at-boundaries`); encode output for its
   context (HTML, SQL, shell, logs).
3. Authorize explicitly per resource (rule `explicit-authorization`); test the forbidden case.
4. Paths: resolve against a fixed root and reject anything that escapes it (`../`, symlinks).
5. Commands: argument lists, no shell, allowlisted executables, timeouts.
6. Secrets: from environment/secret store only; never logged or echoed (policy `secrets`).
7. Dependencies: add only what is needed, from trusted sources; check advisories.

**Verify**: negative tests for forbidden access and malicious input; secret scanning and
dependency audit where the project has them.

**Pitfalls**: trusting client-side checks; verbose error messages leaking internals;
deserializing untrusted data; SSRF through user-supplied URLs.

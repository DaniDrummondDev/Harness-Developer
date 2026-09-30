---
version: 1
id: secrets
type: policy
name: Secrets handling
description: Secrets never enter source control, configuration, logs, prompts, memory or run artifacts.
tags: [security, secrets]
applies_to:
  always: true
---
# Policy: Secrets handling

Mandatory. No task contract, guideline, skill, memory or probabilistic decision can relax it.

1. Never commit secrets (API keys, tokens, passwords, private keys, connection strings with
   credentials, `.env` files) to Git, in any branch, fixture or example.
2. Configuration references a secret by **environment variable name** only
   (e.g. `api_key_env: JEV_API_KEY`), never by value.
3. Never write a secret to logs, error messages, telemetry, prompts, memory or run artifacts.
   Log the *name* of a missing variable, never a value.
4. A secret found in the working tree or history blocks the change: stop, report the location
   (not the value) and require human action to rotate it.
5. Test data uses obvious placeholders (`<api-key>`, `test-key`), never real credentials.
6. Absence of evidence that content is secret-free is not proof it is safe (fail closed).

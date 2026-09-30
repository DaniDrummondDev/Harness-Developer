---
version: 1
id: testing
type: guideline
name: Testing expectations
description: Every behaviour change ships with tests derived from requirements; tests are deterministic, offline and fast by default.
tags: [testing, quality]
applies_to:
  always: true
---
# Guideline: Testing expectations

Recommended practice for every project.

- Every behaviour change or bug fix comes with a test that fails without it.
- Derive tests from requirements, invariants and acceptance criteria, not from the
  implementation you just wrote.
- Default suite is **deterministic, offline and fast**: no network, no real providers, no
  wall-clock or ordering dependence. Live integrations are opt-in and clearly marked.
- Test behaviour through public interfaces; avoid asserting on private details.
- Cover the failure paths (invalid input, missing resources, timeouts), not only the happy path.
- Tests must not depend on the current working directory or on each other.
- A red or skipped required suite is never reported as success.

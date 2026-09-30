---
version: 1
id: testing
type: skill
name: Testing
description: How to design and write effective automated tests - what to test, at which level, and how to keep them deterministic.
tags: [testing, quality]
applies_to:
  always: true
---
# Skill: Testing

**Use when** adding, fixing or reviewing tests.

**How to do it well**
1. Start from the requirement/invariant: write the case that would catch its violation.
2. Pick the level: unit for pure logic, integration for boundaries (DB, filesystem, HTTP
   adapters with emulators), contract tests for interfaces with several implementations,
   end-to-end sparingly.
3. Arrange-Act-Assert; one behaviour per test; descriptive names stating the expectation.
4. Replace external services with fakes/emulators at the adapter boundary; never call real
   paid or remote services in the default suite.
5. Control time, randomness, environment and cwd explicitly (fixtures, injection).
6. Test failure paths: invalid input, missing files, timeouts, permission errors.
7. Regression: reproduce the bug in a failing test before fixing it.

**Verify**: the new test fails without the change and passes with it; the full suite is green.

**Pitfalls**: asserting on implementation details; shared mutable fixtures; order-dependent
tests; over-mocking the unit under test; sleeping instead of synchronizing.

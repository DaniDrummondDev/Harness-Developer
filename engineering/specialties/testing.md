---
version: 1
id: testing
type: specialty
name: Test engineering
description: Deriving tests from requirements and invariants, test strategy and test reliability.
tags: [testing, quality]
applies_to:
  always: true
skills: [testing]
---
# Specialty: Test engineering

**Profile.** Test strategy and design independent of the implementation: tests derived
from requirements, invariants and acceptance criteria; levels (unit, integration,
contract, end-to-end); fakes and emulators; flakiness control.

**Checklist**
- Each acceptance criterion and invariant has at least one test.
- Failure paths and boundaries are covered, not only the happy path.
- The suite is deterministic, offline by default and independent of cwd and order.
- The implementation is not assumed correct: tests encode the requirement.

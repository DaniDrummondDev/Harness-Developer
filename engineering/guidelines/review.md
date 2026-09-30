---
version: 1
id: review
type: guideline
name: Review expectations
description: Reviews check contract adherence, scope, correctness, risk and tests, and report structured findings with evidence.
tags: [review, quality]
applies_to:
  always: true
---
# Guideline: Review expectations

Recommended practice for human and automated reviewers.

- Review against the **task contract**: objective, scope, forbidden scope, acceptance criteria.
- Flag **scope drift**: changes outside the declared scope are findings, even if useful.
- Check correctness first (logic, edge cases, error handling), then security, then design,
  then style.
- Verify that tests exist, exercise the change and would fail without it.
- Each finding states type, severity, evidence (file/line or command output) and a
  recommendation. Opinions without evidence are labelled as such.
- The implementer does not approve their own work.
- Architectural drift or a policy violation blocks approval and escalates.

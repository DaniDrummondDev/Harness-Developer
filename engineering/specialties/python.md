---
version: 1
id: python
type: specialty
name: Python engineering
description: Python application and library engineering - typing, packaging, testing and tooling.
tags: [python, backend]
applies_to:
  stacks: [python]
skills: [python, testing]
rules: [validation-at-boundaries]
---
# Specialty: Python engineering

**Profile.** Modern Python (3.12+) applications and libraries: typed code, Pydantic
validation, packaging with `pyproject.toml`, pytest, Ruff and mypy.

**Checklist**
- Strictly typed public API; mypy clean.
- External data validated into typed models at the boundary.
- No dependence on the current working directory; paths resolved from a known root.
- Tests offline and deterministic; linters green.

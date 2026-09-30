---
version: 1
id: python
type: skill
name: Python
description: How to write, structure and verify modern Python (3.12+) code - typing, packaging, errors and tooling.
tags: [python, backend]
applies_to:
  stacks: [python]
---
# Skill: Python

**Use when** writing or changing Python code.

**How to do it well**
1. Target the project's declared Python version; use modern syntax (`X | None`, `match`,
   PEP 695 generics where supported).
2. Type every public function; run the type checker in strict mode when the project does.
3. Validate external data with typed models (e.g. Pydantic) at the boundary; pass typed
   objects inward. Prefer frozen models/dataclasses for values.
4. Use `pathlib` for paths and resolve them against a known root, never the cwd.
5. Raise specific exception classes from a project hierarchy; never bare `except:`.
6. Run subprocesses with an argument list (no `shell=True`), a timeout and captured output.
7. Keep modules import-light and side-effect free at import time.
8. Use `logging` (to stderr) for diagnostics, never `print` in library code.

**Verify**: the project's `pytest`, `ruff check` and `mypy` (or equivalents) are green.

**Pitfalls**: mutable default arguments; naive datetimes; catching `Exception` to hide bugs;
`yaml.load` without a safe loader; relying on dict/set ordering from external input.

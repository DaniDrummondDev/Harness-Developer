"""Request normalization: raw input from any origin -> `EngineeringRequest`.

    raw strings (CLI args today; MCP/HTTP payloads, task files later)
        -> normalize_request()
        -> EngineeringRequest            (orchestrator/core/request.py)
        -> core.admission.admit()

One generic normalizer serves every source; there is deliberately no
per-source adapter class until an interface needs source-specific parsing
(MCP/HTTP in V14, task files in V6/V13). Interface code (e.g. `cli.py`) calls
this function with plain strings and never builds domain objects itself.

Normalization rules (deterministic, no LLM, no Jev):
- `source`, `mode`, `intent` are matched case-insensitively and `-`/space are
  read as `_` (so "Claude-Code" -> `claude_code`);
- `mode` is optional: when omitted it is derived from the source; when given
  it must agree with the source (checked by the EngineeringRequest invariants);
- `intent` is optional: when omitted it is `UNCLASSIFIED` (never guessed);
- `instruction` and `origin_ref` are stripped; blank `origin_ref` means absent.

Every failure is reported as `InvalidRequestError` listing each problem.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import ValidationError as PydanticValidationError

from orchestrator.core.exceptions import InvalidRequestError
from orchestrator.core.request import (
    EngineeringRequest,
    ExecutionMode,
    Intent,
    RequestSource,
    mode_for_source,
)

_SEPARATORS = re.compile(r"[\s-]+")


def _parse_enum[E: StrEnum](enum: type[E], field: str, raw: str) -> E:
    key = _SEPARATORS.sub("_", raw.strip().lower())
    try:
        return enum(key)
    except ValueError:
        allowed = ", ".join(member.value for member in enum)
        raise InvalidRequestError(f"{field}: unknown value '{raw}' (allowed: {allowed})") from None


def normalize_request(
    *,
    source: str,
    instruction: str,
    intent: str | None = None,
    mode: str | None = None,
    origin_ref: str | None = None,
) -> EngineeringRequest:
    """Build a validated `EngineeringRequest` from raw input.

    Raises:
        InvalidRequestError: unknown source/mode/intent, blank instruction,
            or an EngineeringRequest invariant is violated.
    """
    parsed_source = _parse_enum(RequestSource, "source", source)
    parsed_mode = (
        mode_for_source(parsed_source)
        if mode is None
        else _parse_enum(ExecutionMode, "mode", mode)
    )
    parsed_intent = Intent.UNCLASSIFIED if intent is None else _parse_enum(Intent, "intent", intent)
    ref = origin_ref.strip() if origin_ref is not None else None

    try:
        return EngineeringRequest(
            mode=parsed_mode,
            source=parsed_source,
            intent=parsed_intent,
            instruction=instruction,
            origin_ref=ref or None,
        )
    except PydanticValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'request'}: {err['msg']}"
            for err in exc.errors()
        )
        raise InvalidRequestError(problems) from exc
